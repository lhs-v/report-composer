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
        (w / "pages" / "alpha-01" / "index.html").write_text("<title>비교 페이지</title><style>b{}</style><h2>결과</h2><video src=\"media/v.mp4\"></video>", encoding="utf-8")
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
        status, bad = self.req(f"/api/drafts/{d['id']}", "PUT", {**d, "blocks": [{"id": "x", "type": "spreadsheet"}]})
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
        d["blocks"].insert(0, {"id": "b0", "type": "image", "src": "2026-W42/pages/alpha-01/preview.png", "caption": "캡처", "source_ref": None})
        self.req(f"/api/drafts/{d['id']}", "PUT", d)
        status, exp = self.req(f"/api/export/{d['id']}", "POST", {})
        self.assertEqual(status, 200)
        folder = Path(exp["folder"])
        self.assertTrue((folder / "body.html").exists())
        self.assertTrue((folder / "2026-W42_pages_alpha-01_media_v.mp4").exists())
        paste = (folder / "paste.html").read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", paste)              # images travel inside the file
        self.assertIn("v.mp4", paste)                                 # non-embeddable files are listed by name
        self.assertIn("Ctrl+A", (folder / "읽어주세요.txt").read_text(encoding="utf-8"))
        self.assertEqual(exp["paste_html"], str(folder / "paste.html"))

    def test_whoami_route(self):
        status, who = self.req("/api/confluence/whoami")
        self.assertEqual(status, 200)
        self.assertEqual(who["username"], "hs.lee")

    def test_page_route_wraps_fragment_and_injects_the_picker(self):
        status, body = self.req("/page/2026-W42/pages/alpha-01/index.html")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertTrue(text.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn('<meta name="viewport"', text)
        self.assertIn("<title>비교 페이지</title>", text.split("<body")[0])
        self.assertIn('<base href="/files/2026-W42/pages/alpha-01/">', text)     # relative media keeps working
        self.assertIn('src="/static/picker.js"', text)
        self.assertIn("<h2>결과</h2>", text)
        self.assertEqual(self.req("/page/2026-W42/../x.html")[0], 404)

    def test_pick_image_saves_data_uri_under_the_week_and_returns_a_src(self):
        import base64
        uri = "data:image/png;base64," + base64.b64encode(b"PNG picked").decode()
        status, res = self.req("/api/pick-image", "POST", {"week": "2026-W42", "data": uri, "name": "그림 1"})
        self.assertEqual(status, 200)
        self.assertTrue(res["src"].startswith("2026-W42/picked/"))
        self.assertTrue(res["src"].endswith(".png"))
        self.assertEqual(self.req(f"/files/{res['src']}")[0], 200)
        status, _ = self.req("/api/pick-image", "POST", {"week": "../etc", "data": uri})
        self.assertEqual(status, 400)

    def test_post_without_json_content_type_is_rejected(self):
        status, _ = self.req("/api/drafts", "POST", b'{"title":"x"}', headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)


class ServerV2Tests(unittest.TestCase):
    """A v2 (chapters) package next to a v1 one: /api/library carries chapter metadata."""

    @classmethod
    def setUpClass(cls):
        from tests.test_library_v2 import write_v2_package
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.cfg = Config(inbox_dir=base / "inbox", workspace_dir=base / "ws", port=0, confluence=ConfluenceConfig())
        weeks = cls.cfg.workspace_dir / "weeks"
        write_v2_package(weeks)
        (weeks / "2026-W42").mkdir()
        (weeks / "2026-W42" / "outcomes.json").write_text(json.dumps(OUTCOMES, ensure_ascii=False), encoding="utf-8")
        cls.cfg.inbox_dir.mkdir()
        cls.httpd = make_server("127.0.0.1", 0, cls.cfg)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return resp.status, resp.read()

    def test_library_returns_chapter_metadata(self):
        from tests.test_library_v2 import C1, WEEK
        status, raw = self.get("/api/library")
        self.assertEqual(status, 200)
        lib = {w["week"]: w for w in json.loads(raw)}
        self.assertEqual((lib[WEEK]["schema"], lib["2026-W42"]["schema"]), (2, 1))
        alpha = next(p for p in lib[WEEK]["projects"] if p["short"] == "alpha")
        self.assertEqual((alpha["mode"], alpha["overview"]), ("chapters", "F5 결론과 받아쓰기 도구 정리"))
        ch = alpha["streams"][0]
        self.assertEqual(ch["id"], f"{WEEK}:alpha:{C1}")
        self.assertEqual({k: ch[k] for k in ("kind", "value", "tier", "section")}, {"kind": "결과", "value": "추천", "tier": "main", "section": "결과"})
        self.assertEqual(ch["lead"], "폰에 올릴 위치별 활동 판단 방법은 아직 없다.")
        self.assertEqual([b["label"] for b in ch["blocks"] if b.get("optional")], ["지난주 대비", "근거 작업 단위"])
        gamma = next(p for p in lib[WEEK]["projects"] if p["short"] == "gamma")
        self.assertEqual((gamma["mode"], gamma["one_line"]), ("one_line", "자잘한 설정만 손봤다."))
        img = next(b for b in ch["blocks"] if b["type"] == "image")
        self.assertEqual(self.get(f"/files/{img['src']}"), (200, b"PNG"))
        page = next(b for b in ch["blocks"] if b["type"] == "page")
        self.assertEqual(self.get(f"/page/{page['src']}")[0], 200)


if __name__ == "__main__":
    unittest.main()
