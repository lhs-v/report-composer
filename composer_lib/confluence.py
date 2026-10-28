"""Confluence Data Center REST client (PAT bearer auth) built on urllib, with an injectable transport.

ensure_page() creates the page if there is none; fill_page() uploads every referenced file as an attachment (replace when
a file of that name already exists) and PUTs the storage-format body with the attachment references; publish() is both
for a block draft. The PAT is
only ever placed in the Authorization header; it is excluded from repr() and error messages.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import ConfluenceConfig
from .storage import attachments_for, package_file, render

TIMEOUT = 60


class ConfluenceError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def _urllib_transport(cfg: ConfluenceConfig):
    ctx = ssl.create_default_context(cafile=cfg.ca_bundle or None)
    if not cfg.verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    def transport(method: str, url: str, headers: dict, body: bytes | None):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()
    return transport


class ConfluenceClient:
    def __init__(self, cfg: ConfluenceConfig, transport=None):
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        self.transport = transport or _urllib_transport(cfg)

    def __repr__(self) -> str:
        return f"ConfluenceClient(base_url={self.base!r}, pat={'set' if self.cfg.pat else 'missing'})"

    # ----- low level -----
    def _headers(self, extra: dict | None = None) -> dict:
        if self.cfg.email:   # Confluence Cloud: API token is sent as Basic email:token
            auth = "Basic " + base64.b64encode(f"{self.cfg.email}:{self.cfg.pat}".encode("utf-8")).decode("ascii")
        else:                # Data Center: personal access token as Bearer
            auth = f"Bearer {self.cfg.pat}"
        h = {"Authorization": auth, "Accept": "application/json", "X-Atlassian-Token": "nocheck"}
        h.update(extra or {})
        return h

    def _call(self, method: str, path: str, *, params: dict | None = None, json_body=None, raw: bytes | None = None,
              content_type: str | None = None) -> dict:
        url = f"{self.base}/rest/api/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body, headers = None, {}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw is not None:
            body = raw
            headers["Content-Type"] = content_type or "application/octet-stream"
        status, resp_headers, data = self.transport(method, url, self._headers(headers), body)
        if status >= 400:
            text = data.decode("utf-8", "replace")
            try:
                msg = json.loads(text).get("message") or text[:300]
            except ValueError:
                msg = ("HTML 응답(로그인 페이지로 보임)" if "<html" in text.lower() else text[:300])
            www = next((v for k, v in (resp_headers or {}).items() if k.lower() == "www-authenticate"), None)
            if www:
                msg = f"{msg} [WWW-Authenticate: {www}]"
            raise ConfluenceError(status, str(msg).replace(self.cfg.pat, "***") if self.cfg.pat else str(msg))
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError:
            return {}

    # ----- diagnostics -----
    def whoami(self) -> dict:
        """Who the server thinks we are. The first thing to run when a 401 shows up."""
        u = self._call("GET", "user/current")
        return {"username": u.get("username") or u.get("accountId") or "", "displayName": u.get("displayName") or "",
                "email": u.get("email") or "", "auth": "basic" if self.cfg.email else "bearer", "base_url": self.base}

    # ----- navigation -----
    def spaces(self, limit: int = 50) -> list[dict]:
        res = self._call("GET", "space", params={"limit": limit, "type": "global"})
        return [{"key": s.get("key"), "name": s.get("name")} for s in res.get("results", [])]

    def search_pages(self, space: str, title_query: str, limit: int = 20) -> list[dict]:
        safe = title_query.replace('"', '\\"')
        cql = f'type=page and space="{space}"' + (f' and title~"{safe}"' if safe else "")
        res = self._call("GET", "content/search", params={"cql": cql, "limit": limit})
        return [{"id": str(p.get("id")), "title": p.get("title")} for p in res.get("results", [])]

    def get_page(self, page_id: str) -> dict:
        p = self._call("GET", f"content/{page_id}", params={"expand": "version,space"})
        return {"id": str(p.get("id")), "title": p.get("title"), "version": int(p.get("version", {}).get("number", 1)),
                "space": (p.get("space") or {}).get("key"), "url": self._web_url(p)}

    def _web_url(self, page: dict) -> str:
        webui = (page.get("_links") or {}).get("webui") or ""
        return f"{self.base}{webui}" if webui else f"{self.base}/pages/viewpage.action?pageId={page.get('id')}"

    # ----- writes -----
    def create_page(self, space: str, parent_id: str | None, title: str, body: str) -> dict:
        payload = {"type": "page", "title": title, "space": {"key": space},
                   "body": {"storage": {"value": body, "representation": "storage"}}}
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        p = self._call("POST", "content", json_body=payload)
        return {"id": str(p.get("id")), "version": int(p.get("version", {}).get("number", 1)), "url": self._web_url(p)}

    def update_page(self, page_id: str, title: str, body: str, version: int) -> dict:
        payload = {"id": str(page_id), "type": "page", "title": title, "version": {"number": version, "minorEdit": True},
                   "body": {"storage": {"value": body, "representation": "storage"}}}
        p = self._call("PUT", f"content/{page_id}", json_body=payload)
        return {"id": str(p.get("id")), "version": int(p.get("version", {}).get("number", version)), "url": self._web_url(p)}

    def list_attachments(self, page_id: str) -> dict[str, str]:
        res = self._call("GET", f"content/{page_id}/child/attachment", params={"limit": 200})
        return {a.get("title"): str(a.get("id")) for a in res.get("results", [])}

    def upload_attachment(self, page_id: str, filename: str, data: bytes, existing_att_id: str | None = None) -> str:
        boundary = "----composer" + secrets.token_hex(12)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode("utf-8") + data + \
               f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"minorEdit\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode("utf-8")
        path = f"content/{page_id}/child/attachment" + (f"/{existing_att_id}/data" if existing_att_id else "")
        res = self._call("POST", path, raw=body, content_type=f"multipart/form-data; boundary={boundary}")
        results = res.get("results") or ([res] if res.get("id") else [])
        return str(results[0].get("id")) if results else (existing_att_id or "")

    def ensure_page(self, binding: dict | None, space: str, parent_id: str | None, title: str) -> tuple[str, int, str]:
        """The page a binding points at (its current version), or a new placeholder page under `parent_id`. Returns (page_id, version, url)."""
        if (binding or {}).get("page_id"):
            page = self.get_page(binding["page_id"])
            return page["id"], page["version"], page["url"]
        created = self.create_page(space, parent_id, title, "<p>업로드 중입니다…</p>")
        return created["id"], created["version"], created["url"]

    def fill_page(self, page_id: str, version: int, title: str, blocks: list[dict], weeks_dir: Path) -> dict:
        """Upload the files `blocks` reference to this page (replacing same-named ones), then PUT the body. Returns {page_id, version, url}."""
        existing = self.list_attachments(page_id)
        for filename, src in attachments_for(blocks).items():
            fp = package_file(Path(weeks_dir), src)
            if fp is None:
                continue
            self.upload_attachment(page_id, filename, fp.read_bytes(), existing.get(filename))
        updated = self.update_page(page_id, title, render(blocks), version + 1)
        return {"page_id": page_id, "version": updated["version"], "url": updated["url"]}

    def publish(self, draft: dict, weeks_dir: Path, space: str, parent_id: str | None) -> dict:
        """Create or update the page for a block draft, uploading the files its blocks reference. Returns {page_id, version, url, space, parent_id}."""
        title = draft.get("title") or "제목 없음"
        page_id, version, _ = self.ensure_page(draft.get("confluence"), space, parent_id, title)
        return {**self.fill_page(page_id, version, title, draft.get("blocks") or [], weeks_dir), "space": space, "parent_id": parent_id}
