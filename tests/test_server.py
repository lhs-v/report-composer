import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from composer_lib.config import Config, ConfluenceConfig
from composer_lib.server import make_server
from tests.test_confluence import FakeTransport
from tests.test_library import OUTCOMES


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.cfg = Config(inbox_dir=base / "inbox", workspace_dir=base / "ws", port=0,
                         confluence=ConfluenceConfig(base_url="https://wiki.corp", pat="secret", default_space="AI", default_parent_id="77"))
        w = cls.cfg.workspace_dir / "weeks" / "2026-W42"
        (w / "pages" / "alpha-01" / "media").mkdir(parents=True)
        (w / "outcomes.json").write_text(json.dumps(OUTCOMES, ensure_ascii=False), encoding="utf-8")
        (w / "pages" / "alpha-01" / "preview.png").write_bytes(b"PNG")
        (w / "pages" / "alpha-01" / "media" / "v.mp4").write_bytes(b"MP4")
        cls.cfg.inbox_dir.mkdir()
        cls.transport = FakeTransport()
        cls.httpd = make_server("127.0.0.1", 0, cls.cfg, transport=cls.transport)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def req(self, path, method="GET", data=None, headers=None):
        body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
        h = {"Content-Type": "application/json", **(headers or {})} if body else (headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=body, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if resp.headers.get("Content-Type", "").startswith("application/json") else raw)
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_index_and_state_with_masked_pat(self):
        status, body = self.req("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", body)
        status, state = self.req("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["config"]["confluence"]["pat"], "***")
        self.assertEqual([w["week"] for w in state["weeks"]], ["2026-W42"])
        self.assertNotIn("secret", json.dumps(state))

    def test_library_and_files_are_served_but_not_outside_the_workspace(self):
        status, lib = self.req("/api/library")
        self.assertEqual(status, 200)
        self.assertEqual(lib[0]["projects"][0]["short"], "alpha")
        self.assertEqual(self.req("/files/2026-W42/pages/alpha-01/preview.png")[0], 200)
        self.assertEqual(self.req("/files/2026-W42/../../x")[0], 404)
        self.assertEqual(self.req("/files/..%2F..%2Fx")[0], 404)

    def test_draft_crud_preview_and_publish(self):
        status, d = self.req("/api/drafts", "POST", {"title": "W42 보고"})
        self.assertEqual(status, 200)
        d["blocks"] = [{"id": "b1", "type": "heading", "level": 2, "text": "제목", "source_ref": None},
                       {"id": "b2", "type": "image", "src": "2026-W42/pages/alpha-01/preview.png", "caption": "캡처", "source_ref": None}]
        status, saved = self.req(f"/api/drafts/{d['id']}", "PUT", d)
        self.assertEqual(status, 200)
        self.assertEqual(len(saved["blocks"]), 2)
        status, bad = self.req(f"/api/drafts/{d['id']}", "PUT", {**d, "blocks": [{"id": "x", "type": "table"}]})
        self.assertEqual(status, 400)
        status, prev = self.req("/api/preview", "POST", {"blocks": d["blocks"]})
        self.assertEqual(status, 200)
        self.assertIn("<h2>제목</h2>", prev["xhtml"])
        self.assertIsNone(prev["error"])
        status, res = self.req(f"/api/confluence/publish/{d['id']}", "POST", {"space": "AI", "parent_id": "77"})
        self.assertEqual(status, 200)
        self.assertEqual(res["page_id"], "900")
        status, again = self.req(f"/api/drafts/{d['id']}")
        self.assertEqual(again["confluence"]["page_id"], "900")
        status, dup = self.req(f"/api/drafts/{d['id']}/duplicate", "POST", {})
        self.assertIsNone(dup["confluence"])
        self.assertEqual(self.req(f"/api/drafts/{dup['id']}", "DELETE")[0], 200)

    def test_confluence_lookups_and_export_folder(self):
        status, spaces = self.req("/api/confluence/spaces")
        self.assertEqual(spaces, [{"key": "AI", "name": "AI Lab"}])
        status, pages = self.req("/api/confluence/search?space=AI&q=%EC%A3%BC%EA%B0%84")
        self.assertEqual(pages[0]["id"], "77")
        status, d = self.req("/api/drafts", "POST", {"title": "내보내기"})
        d["blocks"] = [{"id": "b1", "type": "file", "src": "2026-W42/pages/alpha-01/media/v.mp4", "caption": "영상", "source_ref": None}]
        self.req(f"/api/drafts/{d['id']}", "PUT", d)
        status, exp = self.req(f"/api/export/{d['id']}", "POST", {})
        self.assertEqual(status, 200)
        folder = Path(exp["folder"])
        self.assertTrue((folder / "body.html").exists())
        self.assertTrue((folder / "2026-W42_pages_alpha-01_media_v.mp4").exists())

    def test_post_without_json_content_type_is_rejected(self):
        status, _ = self.req("/api/drafts", "POST", b'{"title":"x"}', headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)


if __name__ == "__main__":
    unittest.main()
