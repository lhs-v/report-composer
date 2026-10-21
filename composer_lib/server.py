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

from .config import Config
from .confluence import ConfluenceClient, ConfluenceError
from .drafts import Drafts
from .inbox import process_once, scan
from .library import build_library
from .storage import attachment_name, attachments_for, render, validate

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class App:
    def __init__(self, cfg: Config, transport=None):
        self.cfg = cfg
        self.transport = transport
        self.drafts = Drafts(cfg.workspace_dir)
        self.weeks_dir = cfg.workspace_dir / "weeks"
        self.weeks_dir.mkdir(parents=True, exist_ok=True)
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

    def state(self) -> dict:
        weeks = [{"week": p.name, "has_outcomes": (p / "outcomes.json").exists()} for p in sorted(self.weeks_dir.iterdir(), reverse=True) if p.is_dir()]
        inbox = [s.summary() for s in scan(self.cfg.inbox_dir).values()]
        return {"config": self.cfg.public(), "inbox": inbox, "inbox_status": self.last_inbox, "weeks": weeks,
                "static_ok": (STATIC_DIR / "index.html").exists()}

    def export(self, draft: dict) -> dict:
        folder = self.cfg.workspace_dir / "export" / draft["id"]
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        copied = []
        for name, src in attachments_for(draft.get("blocks") or []).items():
            fp = self.weeks_dir / src
            if fp.is_file():
                shutil.copy2(fp, folder / name)
                copied.append(name)
        (folder / "body.html").write_text(render(draft.get("blocks") or []), encoding="utf-8")
        return {"folder": str(folder), "files": copied}


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
        server_version = "composer/0.1"

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

        def _file(self, path: Path) -> None:
            self._send(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")

        # ----- GET -----
        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            p, q = url.path, urllib.parse.parse_qs(url.query)
            if p == "/":
                f = STATIC_DIR / "index.html"
                return self._file(f) if f.exists() else self._send(200, "<title>composer</title><p>static/index.html missing</p>")
            if p.startswith("/static/"):
                f = _safe_child(STATIC_DIR, p[len("/static/"):])
                return self._file(f) if f else self._send(404, "not found", "text/plain")
            if p.startswith("/files/"):
                f = _safe_child(app.weeks_dir, p[len("/files/"):])
                return self._file(f) if f else self._send(404, "not found", "text/plain")
            if p == "/api/state":
                return self._json(200, app.state())
            if p == "/api/library":
                return self._json(200, build_library(app.weeks_dir))
            if p == "/api/drafts":
                return self._json(200, app.drafts.list())
            m = re.fullmatch(r"/api/drafts/(d-[0-9a-f]+)", p)
            if m:
                d = app.drafts.get(m.group(1))
                return self._json(200, d) if d else self._json(404, {"error": "no such draft"})
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
                hint = " PAT가 만료됐거나 권한이 없습니다." if e.status in (401, 403) else ""
                return self._json(502, {"error": f"Confluence 오류 {e.status}: {e.message}{hint}", "status": e.status})
            except OSError as e:
                msg = str(e)
                hint = " 사내 인증서 문제면 config의 confluence.ca_bundle에 CA 파일 경로를 넣으세요." if "CERTIFICATE" in msg.upper() or "SSL" in msg.upper() else ""
                return self._json(502, {"error": f"연결 실패: {msg[:200]}{hint}"})

        # ----- POST / PUT / DELETE -----
        def do_POST(self):
            p = urllib.parse.urlsplit(self.path).path
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
                xhtml = render(body.get("blocks") or [])
                return self._json(200, {"xhtml": xhtml, "error": validate(xhtml)})
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
                err = validate(render(d.get("blocks") or []))
                if err:
                    return self._json(400, {"error": f"본문 변환 오류: {err}"})

                def go(c):
                    res = c.publish(d, app.weeks_dir, space=space, parent_id=parent)
                    d["confluence"] = res
                    app.drafts.save(d)
                    return res
                return self._confluence(go)
            m = re.fullmatch(r"/api/export/(d-[0-9a-f]+)", p)
            if m:
                d = app.drafts.get(m.group(1))
                return self._json(200, app.export(d)) if d else self._json(404, {"error": "no such draft"})
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
            m = re.fullmatch(r"/api/drafts/(d-[0-9a-f]+)", urllib.parse.urlsplit(self.path).path)
            if not m:
                return self._send(404, "not found", "text/plain")
            body = self._body()
            if body is None:
                return
            body["id"] = m.group(1)
            try:
                return self._json(200, app.drafts.save(body))
            except ValueError as e:
                return self._json(400, {"error": str(e)})

        def do_DELETE(self):
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
