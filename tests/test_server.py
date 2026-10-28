import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from composer_lib.config import Config, ConfluenceConfig
from composer_lib.llm import FakeProvider, FallbackProvider
from composer_lib.llmjobs import JobQueue
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

    def raw(self, path, host, method="GET", headers=None, data=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host, **(headers or {})}
        body = json.dumps(data).encode() if data is not None else None
        if body:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def test_result_pages_live_on_their_own_origin_and_cannot_reach_the_api(self):
        ui, page = f"127.0.0.1:{self.port}", f"localhost:{self.port}"
        status, headers, _ = self.raw("/page/2026-W42/pages/alpha-01/index.html", ui)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], f"http://{page}/page/2026-W42/pages/alpha-01/index.html")
        self.assertEqual(self.raw("/page/2026-W42/pages/alpha-01/index.html", page)[0], 200)
        self.assertEqual(self.raw("/files/2026-W42/pages/alpha-01/preview.png", page)[0], 200)
        self.assertEqual(self.raw("/static/picker.js", page)[0], 200)
        self.assertEqual(self.raw("/api/state", page)[0], 403)                       # a page's own-origin call
        self.assertEqual(self.raw("/api/drafts", ui, "POST", {"Origin": f"http://{page}"}, {"title": "x"})[0], 403)
        self.assertEqual(self.raw("/api/state", "evil.example")[0], 403)             # DNS rebinding
        self.assertEqual(self.raw("/", page)[0], 302)
        status, _, body = self.raw("/api/state", ui)
        self.assertEqual(json.loads(body)["page_origin"], f"http://{page}")
        self.assertEqual(self.raw("/api/drafts", ui, "POST", {"Origin": f"http://{ui}"}, {"title": "ok"})[0], 200)

    def test_raw_package_files_never_run_as_documents_on_either_host(self):
        for host in (f"127.0.0.1:{self.port}",):
            status, headers, _ = self.raw("/files/2026-W42/pages/alpha-01/index.html", host)
            self.assertEqual(status, 200)
            csp = headers.get("Content-Security-Policy", "")
            self.assertIn("sandbox", csp)
            self.assertNotIn("allow-same-origin", csp)
            self.assertNotIn("allow-scripts", csp)

    def test_html_package_files_on_the_page_host_open_as_pages_with_the_picker(self):
        status, headers, _ = self.raw("/files/2026-W42/pages/alpha-01/index.html", f"localhost:{self.port}")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], f"http://localhost:{self.port}/page/2026-W42/pages/alpha-01/index.html")

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

    def test_polish_runs_the_configured_cli_and_opens_the_answer_as_a_new_draft(self):
        import sys
        fake = Path(self.tmp.name) / "fake_gemini.py"
        fake.write_text("import sys\nargs=sys.argv[1:]\nsrc=sys.stdin.read()\n"
                        "assert '-m' in args and args[args.index('-m')+1]=='gemini-test'\n"
                        "prompt=args[args.index('-p')+1]\nassert prompt.isascii()\nassert '[[B:n]]' in src and '쉬운 말' in src\n"
                        "out=['## 다듬은 제목','','메모를 문장으로 풀었다.']\n"
                        "out+=[l for l in src.splitlines() if l.startswith('[[B:')]\n"
                        "print('\\n\\n'.join(out))\n", encoding="utf-8")
        self.cfg.gemini.command = f'"{sys.executable}" "{fake}"'
        status, d = self.req("/api/drafts", "POST", {"title": "거친 초안"})
        d["blocks"] = [{"id": "x1", "type": "paragraph", "text": "맵 만듬. 결과 ok"},
                       {"id": "x2", "type": "image", "src": "2026-W42/pages/alpha-01/preview.png", "caption": "그림"}]
        self.req(f"/api/drafts/{d['id']}", "PUT", d)
        status, res = self.req("/api/polish", "POST", {"draft_id": d["id"], "model": "gemini-test", "instructions": "쉬운 말로"})
        self.assertEqual(status, 200, res)
        new = res["draft"]
        self.assertEqual(new["title"], "거친 초안 · 다듬음")
        self.assertEqual([b["type"] for b in new["blocks"]], ["heading", "paragraph", "image"])
        self.assertEqual(new["blocks"][2]["src"], "2026-W42/pages/alpha-01/preview.png")
        self.assertEqual(new["polished_from"], d["id"])
        status, again = self.req(f"/api/drafts/{d['id']}")
        self.assertEqual(again["blocks"][0]["text"], "맵 만듬. 결과 ok")                    # the rough draft is untouched
        self.cfg.gemini.command = "no-such-gemini-cli"
        status, res = self.req("/api/polish", "POST", {"draft_id": d["id"]})
        self.assertEqual(status, 409)
        err = res if isinstance(res, dict) else json.loads(res)
        self.assertIn("no-such-gemini-cli", err["error"])
        status, _ = self.req("/api/polish", "POST", {"draft_id": "nope"})
        self.assertEqual(status, 400)
        status, _ = self.req("/api/polish", "POST", {"draft_id": d["id"], "style": "shouting"})
        self.assertEqual(status, 400)

    def test_state_tells_the_running_version_and_the_one_on_disk(self):
        from composer_lib import __version__
        status, st = self.req("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(st["version"], __version__)
        self.assertEqual(st["file_version"], __version__)                       # same here; a stale process would differ

    def test_state_tells_the_version_of_the_static_folder(self):
        from composer_lib import __version__
        status, st = self.req("/api/state")
        self.assertEqual(st["static_version"], __version__)                     # code and static/ must be released together

    def test_static_version_is_zero_when_the_meta_is_missing(self):
        from composer_lib import server
        with tempfile.TemporaryDirectory() as d:
            old = server.STATIC_DIR
            try:
                server.STATIC_DIR = Path(d)
                self.assertEqual(server.static_version(), "0")                  # no index.html at all
                (Path(d) / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
                self.assertEqual(server.static_version(), "0")                  # an index.html without the meta
                (Path(d) / "index.html").write_text('<meta name="composer-static" content="1.0.0">', encoding="utf-8")
                self.assertEqual(server.static_version(), "1.0.0")
            finally:
                server.STATIC_DIR = old

    def test_polish_is_gemini_only_and_says_so_when_another_provider_is_chosen(self):
        status, d = self.req("/api/drafts", "POST", {"title": "초안"})
        d["blocks"] = [{"id": "x1", "type": "paragraph", "text": "맵 만듬"}]
        self.req(f"/api/drafts/{d['id']}", "PUT", d)
        self.cfg.llm.provider = "claude"
        status, res = self.req("/api/polish", "POST", {"draft_id": d["id"]})
        self.assertEqual(status, 409)
        err = res if isinstance(res, dict) else json.loads(res)
        self.assertIn("Gemini CLI 전용", err["error"])
        self.cfg.llm.provider = "gemini"                                        # gemini (or nothing chosen) goes on to the polish itself
        self.cfg.gemini.command = "no-such-gemini-cli"
        status, res = self.req("/api/polish", "POST", {"draft_id": d["id"]})
        self.assertEqual(status, 409)
        err = res if isinstance(res, dict) else json.loads(res)
        self.assertIn("no-such-gemini-cli", err["error"])

    def test_a_page_opens_the_720p_copy_where_an_older_package_pointed_home(self):
        from composer_lib.server import substitute_copies
        w = self.cfg.workspace_dir / "weeks" / "2026-W42" / "records" / "alpha" / "R-1"
        w.mkdir(parents=True, exist_ok=True)
        (w / "v.720p.mp4").write_bytes(b"720p")
        (w / "index.html").write_text("<title>영상 페이지</title><video src=\"home:v.mp4\"></video><a href='home:w.mp4'>w</a><img src=\"home:p.png\">", encoding="utf-8")
        status, body = self.req("/page/2026-W42/records/alpha/R-1/index.html")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn('src="v.720p.mp4"', text)                                 # the copy that came along
        self.assertIn("href='home:w.mp4'", text)                                # no copy: still said to be home
        self.assertIn('src="home:p.png"', text)                                 # only videos have copies
        self.assertEqual(substitute_copies('<video src="home:x.mp4">', w), '<video src="home:x.mp4">')

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
        self.assertEqual([b["label"] for b in ch["blocks"] if b.get("optional") and not b.get("in_page")], ["지난주 대비", "근거 작업 단위"])
        gamma = next(p for p in lib[WEEK]["projects"] if p["short"] == "gamma")
        self.assertEqual((gamma["mode"], gamma["one_line"]), ("one_line", "자잘한 설정만 손봤다."))
        img = next(b for b in ch["blocks"] if b["type"] == "image")
        self.assertEqual(self.get(f"/files/{img['src']}"), (200, b"PNG"))
        page = next(b for b in ch["blocks"] if b["type"] == "page")
        self.assertEqual(self.get(f"/page/{page['src']}")[0], 200)


class ServerV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_library_v3 import OUTCOMES_V3, WEEK
        cls.week = WEEK
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.cfg = Config(inbox_dir=base / "inbox", workspace_dir=base / "ws", port=0, path=base / "composer.config.json",
                         confluence=ConfluenceConfig(base_url="https://wiki.corp", pat="secret", default_space="AI", default_parent_id="77"))
        cls.transport = FakeTransport()
        cls.weeks = cls.cfg.workspace_dir / "weeks"
        w = cls.weeks / WEEK
        w.mkdir(parents=True)
        (w / "outcomes.json").write_text(json.dumps(OUTCOMES_V3, ensure_ascii=False), encoding="utf-8")
        (w / "sp-mobile-01-G.md").write_text("# 등급 체계 결론", encoding="utf-8")
        (w / "texts").mkdir()
        (w / "texts" / "U-1.md").write_text("# 응답 발췌\n\n본문", encoding="utf-8")
        for r in OUTCOMES_V3["records"]:
            for fl in r["files"]:
                if fl.get("href"):
                    fp = w / fl["href"]
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_bytes(b"0" * fl["bytes"])
        cls.cfg.inbox_dir.mkdir()
        cls.httpd = make_server("127.0.0.1", 0, cls.cfg, transport=cls.transport)
        cls.port = cls.httpd.server_address[1]
        cls.default_jobs = cls.httpd.app.llm_jobs
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.httpd.app.llm_jobs = self.default_jobs          # a test that plugs in its own queue does not leak it

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

    def test_outline_route_builds_a_tree_and_a_tree_draft_can_be_created(self):
        week = self.week
        code, tree = self.req(f"/api/outline/{week}")
        self.assertEqual(code, 200)
        self.assertEqual(tree["week"], week)
        self.assertEqual(tree["nodes"][tree["root"][0]]["kind"], "summary")
        self.assertEqual(self.req("/api/outline/2030-W01")[0], 404)
        code, d = self.req("/api/drafts/tree", "POST", {"title": "트리", "week": week})
        self.assertEqual((code, d["kind"], d["week"]), (200, "tree", week))
        self.assertEqual(self.req("/api/drafts/tree", "POST", {"title": "x", "week": "2030-W01"})[0], 404)
        code, pv = self.req("/api/preview", "POST", {"draft": d})
        self.assertEqual(code, 200)
        self.assertIn("<h2>", pv["xhtml"])

    def test_memory_caption_round_trips_and_the_tree_uses_it(self):
        from tests.test_library_v3 import R_PAGE
        code, _ = self.req("/api/memory/caption", "PUT", {"record": R_PAGE, "text": ["고친 설명"], "week": self.week})
        self.assertEqual(code, 200)
        self.assertEqual(self.req("/api/memory")[1]["captions"][R_PAGE]["text"], ["고친 설명"])
        tree = self.req(f"/api/outline/{self.week}")[1]
        rec = next(n for n in tree["nodes"].values() if n["kind"] == "record" and n["src"]["record"] == R_PAGE)
        self.assertEqual(rec["caption"], ["고친 설명"])
        for bad in ({"record": 5, "text": ["a"], "week": self.week}, {"record": R_PAGE, "text": "a", "week": self.week},
                    {"record": R_PAGE, "text": ["a", "b", "c"], "week": self.week}, {"record": R_PAGE, "text": [1], "week": self.week},
                    {"record": R_PAGE, "text": ["a"], "week": "W43"}, {"record": R_PAGE, "text": [], "week": "W43"}):
            self.assertEqual(self.req("/api/memory/caption", "PUT", bad)[0], 400, bad)
        # an empty list is "the writer cleared both lines": the memory entry goes, and the seed caption applies again
        self.assertEqual(self.req("/api/memory/caption", "PUT", {"record": R_PAGE, "text": [], "week": self.week})[0], 200)
        self.assertNotIn(R_PAGE, self.req("/api/memory")[1]["captions"])
        self.assertEqual(self.req("/api/memory/caption", "PUT", {"record": R_PAGE, "text": [], "week": self.week})[0], 200)  # again: harmless
        tree = self.req(f"/api/outline/{self.week}")[1]
        rec = next(n for n in tree["nodes"].values() if n["kind"] == "record" and n["src"]["record"] == R_PAGE)
        self.assertNotEqual(rec["caption"], ["고친 설명"])

    def test_an_unreadable_outcomes_file_answers_422_not_a_dropped_connection(self):
        import shutil
        for week, text in (("2026-W50", "{not json"), ("2026-W51", "[]")):
            folder = self.weeks / week
            folder.mkdir()
            self.addCleanup(shutil.rmtree, folder, True)
            (folder / "outcomes.json").write_text(text, encoding="utf-8")
            code, body = self.req(f"/api/outline/{week}")
            self.assertEqual(code, 422, week)
            self.assertIn("error", json.loads(body))
            code, body = self.req("/api/drafts/tree", "POST", {"title": "x", "week": week})
            self.assertEqual(code, 422, week)
            self.assertIn("error", json.loads(body))

    def test_state_reports_when_a_week_folder_last_changed(self):
        import os
        import time
        st = self.req("/api/state")[1]
        w = next(x for x in st["weeks"] if x["week"] == self.week)
        self.assertIsInstance(w["updated"], (int, float))
        ib = self.weeks / self.week / ".inbox-r2.json"
        ib.write_text("{}", encoding="utf-8")
        os.utime(ib, (time.time() + 5, time.time() + 5))
        self.assertGreater(next(x for x in self.req("/api/state")[1]["weeks"] if x["week"] == self.week)["updated"], w["updated"])

    def test_picked_images_are_library_assets(self):
        (self.weeks / self.week / "picked").mkdir(exist_ok=True)
        (self.weeks / self.week / "picked" / "pick-1.png").write_bytes(b"PNG")
        lib = self.req("/api/library")[1]
        week = next(w for w in lib if w["week"] == self.week)
        self.assertTrue(any(a.get("picked") and a["src"] == f"{self.week}/picked/pick-1.png" for a in week["assets"]))

    def _page_draft(self):
        code, d = self.req("/api/drafts/tree", "POST", {"title": "트리", "week": self.week})
        self.assertEqual(code, 200)
        claim = next(n for n in d["nodes"].values() if n["kind"] == "claim" and n["src"]["chapter"] == "C-U-e980fb09-10211943")
        claim["page"] = True
        self.assertEqual(self.req(f"/api/drafts/{d['id']}", "PUT", d)[0], 200)
        return d, claim

    def test_publishing_a_tree_binds_every_page_as_it_is_made_and_a_retry_updates_instead_of_creating(self):
        from tests.test_library_v3 import R_PAGE
        d, claim = self._page_draft()
        t = self.transport
        t.calls.clear()
        t.fail_at = 2                                    # 0 parent create, 1 child create, 2 the child's attachment lookup
        code, _ = self.req(f"/api/confluence/publish/{d['id']}", "POST", {"space": "AI", "title": "트리"})
        self.assertEqual(code, 502)
        saved = self.req(f"/api/drafts/{d['id']}")[1]
        self.assertTrue(saved["confluence"]["page_id"])
        self.assertTrue(saved["pages"][claim["id"]]["page_id"])
        self.assertNotEqual(saved["confluence"]["page_id"], saved["pages"][claim["id"]]["page_id"])
        code, _ = self.req(f"/api/confluence/publish/{d['id']}", "POST", {"space": "AI", "title": "트리"})
        self.assertEqual(code, 200)
        creates = [c for c in t.calls if c["method"] == "POST" and c["url"].endswith("/rest/api/content")]
        self.assertEqual(len(creates), 2)                                           # parent + child, nothing new on the retry
        self.assertEqual(json.loads(creates[1]["body"])["ancestors"][0]["id"], saved["confluence"]["page_id"])
        done = self.req(f"/api/drafts/{d['id']}")[1]
        self.assertEqual(done["confluence"]["page_id"], saved["confluence"]["page_id"])
        self.assertEqual(done["pages"][claim["id"]]["page_id"], saved["pages"][claim["id"]]["page_id"])
        parent_put = [c for c in t.calls if c["method"] == "PUT" and c["url"].endswith("/content/" + done["confluence"]["page_id"])][-1]
        body = json.loads(parent_put["body"])["body"]["storage"]["value"]
        self.assertIn(done["pages"][claim["id"]]["url"], body)                      # the stub became a link to the child page
        self.assertNotIn("[[page:", body)
        self.assertEqual(self.req("/api/memory")[1]["used"][R_PAGE], [self.week])

    def test_publishing_forgets_page_bindings_of_deleted_nodes(self):
        d, claim = self._page_draft()
        self.httpd.app.drafts.save({"id": d["id"], "pages": {"n-gone": {"page_id": "999", "version": 3, "url": "https://wiki.corp/x"}}})   # bindings are server-owned: a PUT cannot plant one
        self.assertEqual(self.req(f"/api/confluence/publish/{d['id']}", "POST", {"space": "AI"})[0], 200)
        self.assertEqual(sorted(self.req(f"/api/drafts/{d['id']}")[1]["pages"]), [claim["id"]])

    def test_export_of_a_tree_writes_child_pages_without_stub_text_and_records_the_use(self):
        import os
        from tests.test_library_v3 import R_FIG
        d, claim = self._page_draft()
        code, res = self.req(f"/api/export/{d['id']}", "POST", {})
        self.assertEqual(code, 200)
        folder = Path(res["folder"])
        self.assertNotIn("[[page:", (folder / "body.html").read_text(encoding="utf-8"))
        self.assertIn("등급 체계 결론", (folder / "page-1.html").read_text(encoding="utf-8"))
        self.assertFalse((folder / "page-2.html").exists())
        readme = (folder / "읽어주세요.txt").read_text(encoding="utf-8")
        self.assertIn("page-1.html", readme)                                              # the instructions say where the child pages went
        self.assertEqual(res["pages"], ["page-1.html"])
        self.assertNotIn("[[page:", (folder / "paste.html").read_text(encoding="utf-8"))
        self.assertTrue(any(f.endswith("preview-top.png") for f in os.listdir(folder)))      # the child page's picture travelled too
        self.assertEqual(self.req("/api/memory")[1]["used"][R_FIG], [self.week])
        code, pasted = self.req(f"/api/paste/{d['id']}", "POST", {})
        self.assertEqual(code, 200)
        self.assertNotIn("[[page:", pasted["html"])

    def test_paste_of_a_tree_is_one_document_with_the_child_pages_inline(self):
        d, claim = self._page_draft()
        rec = next(d["nodes"][c] for c in claim["children"] if d["nodes"][c]["kind"] == "record")
        rec["caption"] = ["자식 페이지에만 있는 문장"]                                            # nowhere in the stub line of the parent body
        self.assertEqual(self.req(f"/api/drafts/{d['id']}", "PUT", d)[0], 200)
        code, pasted = self.req(f"/api/paste/{d['id']}", "POST", {})
        self.assertEqual(code, 200)
        self.assertIn("자식 페이지에만 있는 문장", pasted["html"])
        self.assertEqual(pasted["html"].count("<hr"), 2)                                       # the instruction box + the divider before the child page
        self.assertNotIn("[[page:", pasted["html"])

    def test_preview_of_a_tree_has_no_stub_text(self):
        d, claim = self._page_draft()
        code, pv = self.req("/api/preview", "POST", {"draft": d})
        self.assertEqual(code, 200)
        self.assertNotIn("[[page:", pv["xhtml"])
        self.assertIn("등급 체계 결론", pv["xhtml"])                                             # the stub's own title and lead stay

    def test_a_draft_without_a_week_records_no_use(self):
        d, claim = self._page_draft()
        d["week"] = ""
        self.assertEqual(self.req(f"/api/drafts/{d['id']}", "PUT", d)[0], 200)
        self.assertEqual(self.req(f"/api/paste/{d['id']}", "POST", {})[0], 200)
        self.assertFalse(any("" in weeks for weeks in self.req("/api/memory")[1]["used"].values()))

    def _publish(self, d):
        return self.req(f"/api/confluence/publish/{d['id']}", "POST", {"space": "AI", "title": "트리"})

    def test_the_clients_next_autosave_cannot_wipe_what_a_publish_bound(self):
        d, claim = self._page_draft()                                            # d: the copy the client holds, pages {}
        t = self.transport
        t.calls.clear()
        code, res = self._publish(d)
        self.assertEqual(code, 200)
        self.assertEqual(sorted(res["pages"]), [claim["id"]])                      # the route hands both back, so the client can adopt them
        bound = self.req(f"/api/drafts/{d['id']}")[1]
        self.assertEqual((bound["confluence"]["page_id"], bound["pages"][claim["id"]]["page_id"]), (res["page_id"], res["pages"][claim["id"]]["page_id"]))
        d["title"] = "고친 제목"
        self.assertEqual(self.req(f"/api/drafts/{d['id']}", "PUT", d)[0], 200)      # the stale client copy autosaves
        after = self.req(f"/api/drafts/{d['id']}")[1]
        self.assertEqual(after["title"], "고친 제목")                                # the edit went through
        self.assertEqual((after["pages"], after["confluence"]), (bound["pages"], bound["confluence"]))
        self.assertEqual(self._publish(d)[0], 200)
        creates = [c for c in t.calls if c["method"] == "POST" and c["url"].endswith("/rest/api/content")]
        self.assertEqual(len(creates), 2)                                          # parent + child once; the second publish only updates
        self.assertEqual(json.loads(creates[1]["body"])["title"], f"{claim['title']} — {self.week}")

    def test_an_edit_made_during_a_publish_survives_it(self):
        d, claim = self._page_draft()
        t = self.transport
        seen = []

        def meanwhile(method, path):                                                # the writer types while the upload runs
            if method == "PUT" and not seen:
                seen.append(path)
                self.httpd.app.drafts.save({"id": d["id"], "title": "업로드 중에 고침"})
        t.hook = meanwhile
        self.addCleanup(setattr, t, "hook", None)
        self.assertEqual(self._publish(d)[0], 200)
        done = self.req(f"/api/drafts/{d['id']}")[1]
        self.assertEqual(done["title"], "업로드 중에 고침")
        self.assertTrue(done["pages"][claim["id"]]["page_id"])

    def test_a_taken_page_title_answers_a_readable_hint(self):
        d, claim = self._page_draft()
        t = self.transport
        t.clash = True
        self.addCleanup(setattr, t, "clash", False)
        code, body = self._publish(d)
        self.assertEqual(code, 502)
        self.assertIn("같은 제목의 페이지가 이미 있습니다: 트리", json.loads(body)["error"])

    def test_a_draft_that_is_not_a_tree_answers_422_not_a_traceback(self):
        self.assertEqual(self.req("/api/preview", "POST", {"draft": {"kind": "tree"}})[0], 422)
        node = {"id": "n-a", "kind": "claim", "title": "t", "text": "", "on": True, "folded": False, "page": False, "stale": False,
                "src": {}, "marks": [], "tier": "main", "children": ["n-a"]}
        code, body = self.req("/api/preview", "POST", {"draft": {"kind": "tree", "week": self.week, "nodes": {"n-a": node}, "root": ["n-a"]}})
        self.assertEqual(code, 422)
        self.assertIn("error", json.loads(body))


    def _tree(self):
        d = self.req("/api/drafts/tree", "POST", {"title": "t", "week": self.week})[1]
        return d, next(n for n in d["nodes"].values() if n["kind"] == "claim")

    def test_llm_routes_queue_a_job_and_report_it(self):
        self.httpd.app.llm_jobs = JobQueue(lambda: FallbackProvider(FakeProvider(["새 본문"]), None))
        d, claim = self._tree()
        code, job = self.req("/api/llm/jobs", "POST", {"kind": "node", "draft_id": d["id"], "node_id": claim["id"], "style": "brief"})
        self.assertEqual(code, 202)
        for _ in range(100):
            j = self.req(f"/api/llm/jobs/{job['job']['id']}")[1]
            if j["status"] == "done": break
            time.sleep(0.02)
        self.assertEqual(j["result"]["value"], "새 본문"); self.assertEqual(j["result"]["before"], claim["text"])
        self.assertEqual(self.req("/api/llm/jobs/nope")[0], 404)
        self.assertEqual(self.req("/api/llm/jobs", "POST", {"kind": "poem", "draft_id": d["id"]})[0], 400)
        self.assertEqual(self.req("/api/llm/jobs", "POST", {"kind": "node", "draft_id": "d-ffff", "node_id": claim["id"]})[0], 404)
        self.assertEqual(self.req("/api/llm/jobs", "POST", {"kind": "node", "draft_id": "nope"})[0], 400)

    def test_llm_cancel_route(self):
        gate = threading.Event()

        class Slow(FakeProvider):
            def complete(self, prompt, *, system=None):
                gate.wait(2); return super().complete(prompt, system=system)
        self.addCleanup(gate.set)
        self.httpd.app.llm_jobs = JobQueue(lambda: FallbackProvider(Slow(["늦은 답"]), None))
        d, claim = self._tree()
        job = self.req("/api/llm/jobs", "POST", {"kind": "node", "draft_id": d["id"], "node_id": claim["id"]})[1]["job"]
        self.assertEqual(self.req(f"/api/llm/jobs/{job['id']}/cancel", "POST", {}), (200, {"cancelled": True}))
        self.assertEqual(self.req(f"/api/llm/jobs/{job['id']}")[1]["status"], "cancelled")
        self.assertEqual(self.req("/api/llm/jobs/nope/cancel", "POST", {}), (200, {"cancelled": False}))

    def test_llm_providers_and_config_round_trip(self):
        code, p = self.req("/api/llm/providers")
        self.assertEqual(code, 200); self.assertIn("claude", p["providers"])
        self.assertEqual(set(p["available"]), {"claude", "gemini", "codex"}); self.assertIn("ready", p)
        code, saved = self.req("/api/llm/config", "PUT", {"provider": "gemini", "command": "", "model": "gemini-3.8-flash", "fallback": None})
        self.assertEqual(code, 200); self.assertEqual(saved["llm"]["provider"], "gemini")
        self.assertEqual(self.cfg.llm.provider, "gemini")
        on_disk = json.loads(self.cfg.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["llm"]["model"], "gemini-3.8-flash")
        code, saved = self.req("/api/llm/config", "PUT", {"provider": "claude", "fallback": {"provider": "gemini", "model": "x"}})
        self.assertEqual((code, saved["llm"]["fallback"]["provider"]), (200, "gemini"))
        for bad in ({"provider": "banana"}, {"provider": "claude", "command": 5}, {"provider": "claude", "fallback": {"provider": "banana"}},
                    {"provider": "claude", "fallback": "gemini"}):
            self.assertEqual(self.req("/api/llm/config", "PUT", bad)[0], 400, bad)
        self.assertEqual(self.cfg.llm.provider, "claude")                       # a refused change leaves the config alone

    def test_llm_config_without_a_config_path_is_a_409(self):
        app = self.httpd.app
        path, app.cfg.path = app.cfg.path, None
        self.addCleanup(setattr, app.cfg, "path", path)
        self.assertEqual(self.req("/api/llm/config", "PUT", {"provider": "claude"})[0], 409)

    def test_llm_test_call_uses_the_main_provider(self):
        app = self.httpd.app
        app.llm_provider = lambda: FallbackProvider(FakeProvider(["OK"]), FakeProvider(["fallback"]))
        self.addCleanup(delattr, app, "llm_provider")
        code, r = self.req("/api/llm/test", "POST", {})
        self.assertEqual((code, r["ok"], r["answer"]), (200, True, "OK")); self.assertIn("ms", r)
        app.llm_provider = lambda: None
        code, r = self.req("/api/llm/test", "POST", {})
        self.assertEqual((code, r["ok"]), (200, False)); self.assertTrue(r["error"])
        app.llm_provider = lambda: FallbackProvider(FakeProvider([]), None)
        self.assertFalse(self.req("/api/llm/test", "POST", {})[1]["ok"])

    def test_llm_test_call_can_try_settings_that_are_not_saved(self):
        app = self.httpd.app
        seen, before = [], app.cfg.llm
        app.llm_provider = lambda llm=None: seen.append(llm) or FallbackProvider(FakeProvider(["OK"]), None)
        self.addCleanup(delattr, app, "llm_provider")
        self.assertTrue(self.req("/api/llm/test", "POST", {"provider": "gemini", "model": "m1"})[1]["ok"])
        self.assertEqual((seen[0].provider, seen[0].model), ("gemini", "m1"))     # the form's values, not the saved config
        self.assertIs(app.cfg.llm, before)                                        # and nothing was saved
        code, r = self.req("/api/llm/test", "POST", {"provider": "nope"})
        self.assertEqual((code, r["ok"]), (200, False)); self.assertEqual(len(seen), 1)

    def test_jobs_are_refused_without_a_provider(self):
        self.httpd.app.llm_jobs = JobQueue(lambda: None)
        d = self.req("/api/drafts/tree", "POST", {"title": "t", "week": self.week})[1]
        code, r = self.req("/api/llm/jobs", "POST", {"kind": "summary", "draft_id": d["id"]})
        self.assertEqual((code, json.loads(r).get("code")), (409, "NO_PROVIDER"))

    def test_a_bad_job_request_is_a_400_before_anything_else(self):
        self.httpd.app.llm_jobs = JobQueue(lambda: None)                        # not ready, yet bad input still answers 400 first
        d = self.req("/api/drafts/tree", "POST", {"title": "t", "week": self.week})[1]
        self.assertEqual(self.req("/api/llm/jobs", "POST", {"kind": "poem", "draft_id": d["id"]})[0], 400)
        self.assertEqual(self.req("/api/llm/jobs", "POST", {"kind": "summary", "draft_id": d["id"], "style": "slang"})[0], 400)
        self.assertEqual(self.req("/api/llm/jobs", "POST", ["summary"])[0], 400)

    def test_llm_routes_answer_the_composer_window_only(self):
        code, _ = self.req("/api/llm/providers", headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(code, 403)
        self.assertEqual(self.req("/api/llm/config", "PUT", {"provider": "claude"}, headers={"Origin": "http://evil.example"})[0], 403)

    def test_a_default_app_gets_a_real_provider_factory(self):
        app = self.httpd.app
        cfg = app.cfg.llm
        saved = (cfg.provider, cfg.command, cfg.model, cfg.fallback)
        self.addCleanup(lambda: (setattr(cfg, "provider", saved[0]), setattr(cfg, "command", saved[1]),
                                 setattr(cfg, "model", saved[2]), setattr(cfg, "fallback", saved[3])))
        cfg.provider, cfg.command, cfg.model, cfg.fallback = "", "", "", None
        self.assertIsNone(app.llm_provider())
        cfg.provider, cfg.command = "claude", "no-such-claude-binary-xyz"
        prov = app.llm_provider()
        self.assertEqual((prov.primary.spec.provider, str(prov.primary.cwd), prov.fallback), ("claude", str(app.cfg.workspace_dir), None))
        self.assertFalse(app.llm_jobs.ready())                                  # the command is not on this machine


if __name__ == "__main__":
    unittest.main()
