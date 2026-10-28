"""Local HTTP server for the composer UI. Standard library only; binds to 127.0.0.1.

Routes
  GET  /                      editor page            GET  /static/<file>           UI assets
  GET  /files/<week>/<path>   package files          GET  /api/state               config (masked), inbox, weeks
  GET  /api/library           blocks per week        GET  /api/drafts              list
  POST /api/drafts {title}    create                 GET/PUT/DELETE /api/drafts/<id>
  POST /api/drafts/<id>/duplicate                    POST /api/preview {blocks} -> {xhtml, error}
  GET  /api/confluence/spaces                        GET  /api/confluence/search?space=&q=
  POST /api/confluence/publish/<id> {space, parent_id, title?}
  POST /api/export/<id>       folder with body.html + referenced files
  POST /api/open {path}       open a workspace path in Explorer
  GET  /api/outline/<week>    draft tree      POST /api/drafts/tree {title, week}
  GET  /api/memory            captions/uses   PUT /api/memory/caption {record, text, week}
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .config import Config
from .confluence import ConfluenceClient, ConfluenceError
from .drafts import Drafts
from .inbox import process_once, scan
from .library import build_library
from .memory import Memory
from .pastehtml import paste_html, readme_text
from .storage import attachment_name, attachments_for, package_file, render, validate

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class OutlineError(Exception):
    """outcomes.json exists but cannot be turned into a draft tree (corrupt JSON, wrong shape)."""


class App:
    def __init__(self, cfg: Config, transport=None):
        self.cfg = cfg
        self.transport = transport
        self.drafts = Drafts(cfg.workspace_dir)
        self.weeks_dir = cfg.workspace_dir / "weeks"
        self.weeks_dir.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(cfg.workspace_dir / "memory.json")
        self.lock = threading.Lock()
        self.last_inbox: dict = {"checked": None, "extracted": [], "error": None}

    def inbox_tick(self) -> None:
        try:
            with self.lock:
                extracted = process_once(self.cfg.inbox_dir, self.cfg.workspace_dir)
            self.last_inbox = {"checked": time.strftime("%H:%M:%S"), "extracted": extracted, "error": None}
        except Exception as e:  # noqa: BLE001
            self.last_inbox = {"checked": time.strftime("%H:%M:%S"), "extracted": [], "error": str(e)[:200]}

    def client(self) -> ConfluenceClient:
        return ConfluenceClient(self.cfg.confluence, transport=self.transport)

    def outline(self, week: str) -> dict:
        from .outline import build_tree
        meta = self.weeks_dir / week / "outcomes.json"
        if not re.fullmatch(r"\d{4}-W\d{2}", week) or not meta.is_file():
            raise KeyError(week)
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            return build_tree(data, week, self.memory.data())
        except (OSError, ValueError, AttributeError, TypeError) as e:
            raise OutlineError(f"outcomes.json을 읽지 못했습니다: {type(e).__name__}") from e

    @staticmethod
    def used_ids(draft: dict) -> list[str]:
        """The records and chapters of every node that is on (an off node takes its subtree with it)."""
        nodes, ids = draft.get("nodes") or {}, set()

        def walk(nid: str) -> None:
            n = nodes.get(nid)
            if not n or not n.get("on"):
                return
            src = n.get("src") or {}
            ids.update(i for i in (src.get("record"), src.get("chapter")) if i and i != "loose")
            for c in n.get("children") or []:
                walk(c)
        for rid in draft.get("root") or []:
            walk(rid)
        return sorted(ids)

    def publish_tree(self, draft: dict, space: str, parent_id: str | None, client: ConfluenceClient) -> dict:
        """Parent page, one child page per `page` node, then the parent again with links to them. Every page id is saved the moment
        the page exists, so a failure anywhere leaves a draft whose retry updates those pages instead of making new ones."""
        from .outline import link_stubs, to_blocks
        title = draft.get("title") or "제목 없음"
        main, pages = to_blocks(draft)
        bound = {k: v for k, v in (draft.get("pages") or {}).items() if k in draft["nodes"]}   # a deleted node's page stays on the wiki, not in the draft
        draft["pages"] = bound
        # Only the server-owned fields are saved, never the whole `draft` snapshot: the writer keeps typing during a multi-second
        # upload, and save() merges, so the nodes and text edited meanwhile stay as they are.
        did = draft["id"]
        page_id, version, url = client.ensure_page(draft.get("confluence"), space, parent_id, title)
        confluence = {"page_id": page_id, "version": version, "url": url, "space": space, "parent_id": parent_id}
        self.drafts.save({"id": did, "title": title, "confluence": confluence, "pages": bound})
        for pg in pages:
            cid, cver, curl = client.ensure_page(bound.get(pg["node"]), space, page_id, pg["title"])
            bound[pg["node"]] = {"page_id": cid, "version": cver, "url": curl}
            self.drafts.save({"id": did, "pages": bound})
        links = {pg["node"]: bound[pg["node"]]["url"] for pg in pages}
        for pg in pages:
            b = bound[pg["node"]]
            bound[pg["node"]] = client.fill_page(b["page_id"], b["version"], pg["title"], link_stubs(pg["blocks"], links), self.weeks_dir)
            self.drafts.save({"id": did, "pages": bound})
        confluence = {**client.fill_page(page_id, version, title, link_stubs(main, links), self.weeks_dir), "space": space, "parent_id": parent_id}
        self.drafts.save({"id": did, "confluence": confluence, "pages": bound})
        draft["confluence"], draft["pages"] = confluence, bound
        self.note_used(draft)
        return confluence

    def export_blocks(self, draft: dict) -> tuple[list[dict], list[list[dict]]]:
        """The blocks of the folder and copy-paste exports, with no child-page stub text in them. A tree's child pages come as separate lists."""
        if draft.get("kind") != "tree":
            return draft.get("blocks") or [], []
        from .outline import link_stubs, to_blocks
        main, pages = to_blocks(draft)
        return link_stubs(main, {}), [link_stubs(pg["blocks"], {}) for pg in pages]

    def note_used(self, draft: dict) -> None:
        if draft.get("kind") == "tree" and draft.get("week"):
            self.memory.mark_used(self.used_ids(draft), draft["week"])

    @staticmethod
    def week_updated(folder: Path) -> float:
        times = [p.stat().st_mtime for p in [folder / "outcomes.json", *folder.glob(".inbox*.json")] if p.exists()]
        return max(times) if times else folder.stat().st_mtime

    def state(self) -> dict:
        weeks = [{"week": p.name, "has_outcomes": (p / "outcomes.json").exists(), "updated": self.week_updated(p)} for p in sorted(self.weeks_dir.iterdir(), reverse=True) if p.is_dir()]
        inbox = [s.summary() for s in scan(self.cfg.inbox_dir, self.cfg.workspace_dir).values()]
        return {"config": self.cfg.public(), "version": __version__, "file_version": installed_version(),
                "gemini": {"model": self.cfg.gemini.model, "command": self.cfg.gemini.command},
                "inbox": inbox, "inbox_status": self.last_inbox, "weeks": weeks,
                "static_ok": (STATIC_DIR / "index.html").exists()}

    def export(self, draft: dict) -> dict:
        folder = self.cfg.workspace_dir / "export" / draft["id"]
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        blocks, pages = self.export_blocks(draft)
        copied = []
        for name, src in attachments_for(blocks + [b for pg in pages for b in pg]).items():
            fp = package_file(self.weeks_dir, src)
            if fp:
                shutil.copy2(fp, folder / name)
                copied.append(name)
        (folder / "body.html").write_text(render(blocks), encoding="utf-8")
        for n, pg in enumerate(pages, 1):
            (folder / f"page-{n}.html").write_text(render(pg), encoding="utf-8")
        doc, manual = paste_html(draft.get("title") or "제목 없음", blocks, self.weeks_dir)
        (folder / "paste.html").write_text(doc, encoding="utf-8")
        page_files = [f"page-{n}.html" for n in range(1, len(pages) + 1)]
        (folder / "읽어주세요.txt").write_text(readme_text(draft.get("title") or "제목 없음", manual, page_files), encoding="utf-8")
        self.note_used(draft)
        return {"folder": str(folder), "files": copied, "paste_html": str(folder / "paste.html"), "manual_files": manual, "pages": page_files}

    def save_picked_image(self, week: str, data_uri: str, name: str = "") -> str:
        """Store an image picked out of a result page as a package-relative file so it can be attached later."""
        import base64
        import hashlib
        head, _, b64 = data_uri.partition(",")
        mime = head[5:].split(";")[0]
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg"}.get(mime)
        if not ext or not b64:
            raise ValueError("지원하지 않는 이미지 형식")
        raw = base64.b64decode(b64)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("이미지가 10MB를 넘습니다")
        folder = self.weeks_dir / week / "picked"
        folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:24] or "pick"
        fname = f"{stem}-{hashlib.sha1(raw).hexdigest()[:8]}{ext}"
        (folder / fname).write_bytes(raw)
        return f"{week}/picked/{fname}"

    def paste(self, draft: dict) -> dict:
        main, pages = self.export_blocks(draft)
        for n, pg in enumerate(pages, 1):                       # one clipboard document: the child pages follow the body, each after a divider
            main = [*main, {"id": f"b-page-{n}-divider", "type": "divider", "source_ref": None}, *pg]
        doc, manual = paste_html(draft.get("title") or "제목 없음", main, self.weeks_dir)
        self.note_used(draft)
        return {"html": doc, "manual_files": manual}


PAGE_BASE_CSS = ("html,body{margin:0;padding:0}body{font-family:'Noto Sans KR','Malgun Gothic',system-ui,sans-serif;font-size:14px;line-height:1.5;"
                 "padding:12px 16px;color:#1c2320;background:#fff}img,video,canvas{max-width:100%}")


def installed_version() -> str | None:
    """The version written in composer_lib/__init__.py on disk — after a zip is unpacked over a running composer
    it differs from the imported one until the process is restarted, and the title bar says so."""
    try:
        text = (Path(__file__).resolve().parent / "__init__.py").read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else None
    except OSError:
        return None


def wrap_page(fragment: str, base_href: str) -> str:
    """Give an artifact-style fragment a real document head (the Claude viewer used to add one), point relative
    media at /files/, and inject the element picker so the composer can lift pieces out of the page."""
    low = fragment.lower()
    m = re.search(r"<title>(.*?)</title>", fragment, re.S)
    title = m.group(1) if m else "page"
    body = fragment.replace(m.group(0), "", 1) if m else fragment
    picker = '<script src="/static/picker.js"></script>'
    if "<html" in low:
        # a complete document: inject base + picker without disturbing the rest
        out = re.sub(r"<head([^>]*)>", lambda mm: f"<head{mm.group(1)}><base href=\"{base_href}\">", fragment, count=1, flags=re.I)
        return re.sub(r"</body>", picker + "</body>", out, count=1, flags=re.I) if "</body>" in out.lower() else out + picker
    return ("<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<base href=\"{base_href}\"><title>{title}</title><style>{PAGE_BASE_CSS}</style></head><body>"
            f"{body}{picker}</body></html>")


_HOME_REF = re.compile(r"""(?P<q>["'])home:(?P<name>[^"']+?)\.(?:mp4|webm|mov)(?P=q)""")


def substitute_copies(html: str, folder: Path) -> str:
    """Packages before 2026-10-26 pointed a page's video at `home:<name>.mp4` even when `<name>.720p.mp4` came
    along: open the copy where it exists."""
    def swap(m: re.Match) -> str:
        q, name = m.group("q"), m.group("name")
        copy = f"{name}.720p.mp4"
        return f"{q}{copy}{q}" if (folder / copy).is_file() else m.group(0)
    return _HOME_REF.sub(swap, html)


def _safe_child(base: Path, rel: str) -> Path | None:
    rel = urllib.parse.unquote(rel)
    if "\x00" in rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
        return None
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"composer/{__version__}"

        def log_message(self, fmt, *args):
            sys.stdout.write(f"[http] {fmt % args}\n")
            sys.stdout.flush()

        # ----- helpers -----
        def _send(self, code: int, body: bytes | str, ctype="text/html; charset=utf-8", extra: dict | None = None):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

        def _body(self):
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._send(415, "application/json expected", "text/plain; charset=utf-8")
                return None
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._json(400, {"error": "invalid JSON"})
                return None

        # ----- origins -----
        # The UI and its API live on 127.0.0.1; result pages (agent-made HTML that arrived by mail) only on the page
        # host. Two origins: a page's scripts cannot read or call the API, and the picker reaches the UI by message.
        def _origins(self) -> tuple[str, str]:
            port = self.server.server_address[1]
            return f"127.0.0.1:{port}", f"{app.cfg.page_host}:{port}"

        def _guard(self, path: str) -> bool:
            """False (and the response already sent) when the request may not go on."""
            ui, page = self._origins()
            host = self.headers.get("Host", "")
            if host not in (ui, page):
                self._send(403, "unknown host", "text/plain")
                return False
            if path.startswith("/page/") and host != page:
                self._send(302, "", "text/plain", {"Location": f"http://{page}{self.path}"})
                return False
            if path == "/" and host != ui:
                self._send(302, "", "text/plain", {"Location": f"http://{ui}/"})
                return False
            if path.startswith("/api/") and host != ui:
                self._send(403, "the API answers the composer window only", "text/plain")
                return False
            origin = self.headers.get("Origin")
            if self.command not in ("GET", "HEAD") and origin is not None and origin != f"http://{ui}":
                self._send(403, "cross-origin write refused", "text/plain")
                return False
            return True

        def _file(self, path: Path) -> None:
            self._send(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")

        # ----- GET -----
        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            p, q = url.path, urllib.parse.parse_qs(url.query)
            if not self._guard(p):
                return
            if p == "/":
                f = STATIC_DIR / "index.html"
                return self._file(f) if f.exists() else self._send(200, "<title>composer</title><p>static/index.html missing</p>")
            if p.startswith("/static/"):
                f = _safe_child(STATIC_DIR, p[len("/static/"):])
                return self._file(f) if f else self._send(404, "not found", "text/plain")
            if p.startswith("/files/"):
                f = _safe_child(app.weeks_dir, p[len("/files/"):])
                if not f:
                    return self._send(404, "not found", "text/plain")
                if f.suffix.lower() in (".html", ".htm") and self.headers.get("Host") == self._origins()[1]:
                    # a link between result pages: open the next page the same way, with its head and the picker
                    return self._send(302, "", "text/plain", {"Location": f"http://{self._origins()[1]}/page/{p[len('/files/'):]}"})
                # raw package files are media for pages and the UI; opened as a document (an .html copy, an svg)
                # they get no scripts and no origin, so nothing in them runs as the composer window
                return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream",
                                  {"Content-Security-Policy": "sandbox"})
            if p.startswith("/page/"):
                rel = p[len("/page/"):]
                f = _safe_child(app.weeks_dir, rel)
                if not f or f.suffix.lower() not in (".html", ".htm"):
                    return self._send(404, "not found", "text/plain")
                html = substitute_copies(f.read_text(encoding="utf-8", errors="replace"), f.parent)
                return self._send(200, wrap_page(html, "/files/" + urllib.parse.unquote(rel).rsplit("/", 1)[0] + "/"))
            if p == "/api/state":
                return self._json(200, {**app.state(), "page_origin": f"http://{self._origins()[1]}"})
            if p == "/api/library":
                return self._json(200, build_library(app.weeks_dir))
            m = re.fullmatch(r"/api/outline/(\d{4}-W\d{2})", p)
            if m:
                try:
                    return self._json(200, app.outline(m.group(1)))
                except KeyError:
                    return self._json(404, {"error": "그 주차의 outcomes.json이 없습니다"})
                except OutlineError as e:
                    return self._json(422, {"error": str(e)})
            if p == "/api/memory":
                return self._json(200, app.memory.data())
            if p == "/api/drafts":
                return self._json(200, app.drafts.list())
            m = re.fullmatch(r"/api/drafts/(d-[0-9a-f]+)", p)
            if m:
                d = app.drafts.get(m.group(1))
                return self._json(200, d) if d else self._json(404, {"error": "no such draft"})
            if p == "/api/confluence/whoami":
                return self._confluence(lambda c: c.whoami())
            if p == "/api/confluence/spaces":
                return self._confluence(lambda c: c.spaces())
            if p == "/api/confluence/search":
                space = (q.get("space") or [app.cfg.confluence.default_space])[0]
                return self._confluence(lambda c: c.search_pages(space, (q.get("q") or [""])[0]))
            return self._send(404, "not found", "text/plain")

        def _confluence(self, fn):
            if not app.cfg.confluence.configured:
                return self._json(400, {"error": "Confluence가 설정되지 않았습니다 (composer.config.json의 confluence.base_url, pat)."})
            try:
                return self._json(200, fn(app.client()))
            except ConfluenceError as e:
                mode = "Basic(email+토큰)" if app.cfg.confluence.email else "Bearer(PAT)"
                hint = ""
                if e.status == 401:
                    hint = (f" 현재 인증 방식은 {mode}입니다. Data Center(주소에 pageId= 또는 /spaces/KEY/pages/번호, /wiki 없음)면 email을 비우고 PAT를, "
                            "Cloud(atlassian.net 또는 /wiki 포함)면 email과 API 토큰을 넣으세요. 토큰 만료·재발급도 확인하세요.")
                elif e.status == 403:
                    hint = " 인증은 됐지만 권한이 없습니다. 스페이스/페이지 권한을 확인하세요."
                return self._json(502, {"error": f"Confluence 오류 {e.status}: {e.message}{hint}", "status": e.status})
            except OSError as e:
                msg = str(e)
                hint = " 사내 인증서 문제면 config의 confluence.ca_bundle에 CA 파일 경로를 넣으세요." if "CERTIFICATE" in msg.upper() or "SSL" in msg.upper() else ""
                return self._json(502, {"error": f"연결 실패: {msg[:200]}{hint}"})

        # ----- POST / PUT / DELETE -----
        def do_POST(self):
            p = urllib.parse.urlsplit(self.path).path
            if not self._guard(p):
                return
            body = self._body()
            if body is None:
                return
            if p == "/api/drafts":
                return self._json(200, app.drafts.create(str(body.get("title") or "제목 없음")))
            m = re.fullmatch(r"/api/drafts/(d-[0-9a-f]+)/duplicate", p)
            if m:
                try:
                    return self._json(200, app.drafts.duplicate(m.group(1)))
                except KeyError:
                    return self._json(404, {"error": "no such draft"})
            if p == "/api/preview":
                try:
                    blocks = app.export_blocks(body["draft"])[0] if isinstance(body.get("draft"), dict) else (body.get("blocks") or [])
                    xhtml = render(blocks)
                except (KeyError, TypeError, ValueError, RecursionError) as e:    # a draft body that is not a whole tree (no nodes, a cycle)
                    return self._json(422, {"error": f"초안 모양이 잘못됐습니다: {type(e).__name__}"})
                return self._json(200, {"xhtml": xhtml, "error": validate(xhtml)})
            if p == "/api/polish":
                from .polish import PolishError, polish_draft
                did = str(body.get("draft_id") or "")
                if not re.fullmatch(r"d-[0-9a-f]+", did):
                    return self._json(400, {"error": "draft_id"})
                model = str(body.get("model") or app.cfg.gemini.model)[:80]
                instructions = str(body.get("instructions") or "")[:4000]
                style = str(body.get("style") or "brief")
                if style not in ("polite", "brief", "plain"):
                    return self._json(400, {"error": "style"})
                try:
                    new = polish_draft(app.drafts, did, model=model, instructions=instructions, command=app.cfg.gemini.command,
                                       cwd=app.cfg.workspace_dir, style=style)
                except PolishError as e:
                    return self._json(409, {"error": str(e)})
                except Exception as e:  # noqa: BLE001
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
                return self._json(200, {"draft": new})
            m = re.fullmatch(r"/api/confluence/publish/(d-[0-9a-f]+)", p)
            if m:
                d = app.drafts.get(m.group(1))
                if not d:
                    return self._json(404, {"error": "no such draft"})
                if body.get("title"):
                    d["title"] = body["title"]
                space = body.get("space") or app.cfg.confluence.default_space
                parent = body.get("parent_id") or app.cfg.confluence.default_parent_id or None
                if not space:
                    return self._json(400, {"error": "스페이스 키가 필요합니다."})
                main, pages = app.export_blocks(d)
                err = next((e for e in (validate(render(bl)) for bl in [main, *pages]) if e), None)
                if err:
                    return self._json(400, {"error": f"본문 변환 오류: {err}"})

                def go(c):
                    if d.get("kind") == "tree":
                        res = app.publish_tree(d, space, parent, c)
                        return {**res, "pages": d["pages"]}          # the client adopts both: its copy of the draft still has pages {}
                    res = c.publish(d, app.weeks_dir, space=space, parent_id=parent)
                    d["confluence"] = res
                    app.drafts.save(d)
                    return res
                return self._confluence(go)
            m = re.fullmatch(r"/api/export/(d-[0-9a-f]+)", p)
            if m:
                d = app.drafts.get(m.group(1))
                return self._json(200, app.export(d)) if d else self._json(404, {"error": "no such draft"})
            m = re.fullmatch(r"/api/paste/(d-[0-9a-f]+)", p)
            if m:
                d = app.drafts.get(m.group(1))
                return self._json(200, app.paste(d)) if d else self._json(404, {"error": "no such draft"})
            if p == "/api/pick-image":
                week, data = str(body.get("week") or ""), str(body.get("data") or "")
                if not re.fullmatch(r"\d{4}-W\d{2}", week) or not data.startswith("data:image/"):
                    return self._json(400, {"error": "week 또는 data 형식이 잘못됐습니다."})
                try:
                    src = app.save_picked_image(week, data, str(body.get("name") or ""))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, {"src": src})
            if p == "/api/drafts/tree":
                week = str(body.get("week") or "")
                try:
                    tree = app.outline(week)
                except KeyError:
                    return self._json(404, {"error": "그 주차의 outcomes.json이 없습니다"})
                except OutlineError as e:
                    return self._json(422, {"error": str(e)})
                return self._json(200, app.drafts.create_tree(str(body.get("title") or f"주간 보고 {week}"), week, tree))
            if p == "/api/open":
                target = Path(str(body.get("path") or "")).resolve()
                try:
                    target.relative_to(app.cfg.workspace_dir.resolve())
                except ValueError:
                    return self._json(403, {"error": "workspace 밖 경로는 열 수 없습니다."})
                if not target.exists():
                    return self._json(404, {"error": "경로가 없습니다."})
                if sys.platform == "win32":
                    os.startfile(str(target))  # noqa: S606 - local tool, path confined to workspace
                else:
                    subprocess.Popen(["xdg-open", str(target)])
                return self._json(200, {"opened": str(target)})
            return self._send(404, "not found", "text/plain")

        def do_PUT(self):
            if not self._guard(urllib.parse.urlsplit(self.path).path):
                return
            if urllib.parse.urlsplit(self.path).path == "/api/memory/caption":
                body = self._body()
                if body is None:
                    return
                rid, text, week = body.get("record"), body.get("text"), body.get("week")
                if (not isinstance(rid, str) or not rid or not isinstance(text, list) or len(text) > 2
                        or not all(isinstance(x, str) for x in text) or not isinstance(week, str) or not re.fullmatch(r"\d{4}-W\d{2}", week)):
                    return self._json(400, {"error": "record(문자열), text(문자열 0~2개; 빈 목록은 기억을 지움), week(YYYY-Www)가 필요합니다."})
                if text:
                    app.memory.set_caption(rid, text, week)
                else:
                    app.memory.clear_caption(rid)
                return self._json(200, {"ok": True})
            m = re.fullmatch(r"/api/drafts/(d-[0-9a-f]+)", urllib.parse.urlsplit(self.path).path)
            if not m:
                return self._send(404, "not found", "text/plain")
            body = self._body()
            if body is None:
                return
            body["id"] = m.group(1)
            stored = app.drafts.get(body["id"])
            if stored and stored.get("kind") == "tree":
                body.pop("pages", None)           # the Confluence bindings are the server's: a client copy from before a publish must not wipe them
                body.pop("confluence", None)
            try:
                return self._json(200, app.drafts.save(body))
            except ValueError as e:
                return self._json(400, {"error": str(e)})

        def do_DELETE(self):
            if not self._guard(urllib.parse.urlsplit(self.path).path):
                return
            m = re.fullmatch(r"/api/drafts/(d-[0-9a-f]+)", urllib.parse.urlsplit(self.path).path)
            if not m:
                return self._send(404, "not found", "text/plain")
            app.drafts.delete(m.group(1))
            return self._json(200, {"deleted": m.group(1)})

    return Handler


def make_server(host: str, port: int, cfg: Config, transport=None) -> ThreadingHTTPServer:
    app = App(cfg, transport=transport)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    httpd.app = app  # type: ignore[attr-defined]
    return httpd


def start_inbox_thread(app: App, interval: float = 3.0) -> threading.Thread:
    def loop():
        while True:
            app.inbox_tick()
            time.sleep(interval)
    t = threading.Thread(target=loop, name="inbox", daemon=True)
    t.start()
    return t
