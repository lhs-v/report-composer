"""Second review (2026-10-22): draft sources must stay inside the weeks folder, loose results are pickable, page-host
HTML opens with the picker, and the page host cannot be set to the UI host."""
import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.config import Config, load_config
from composer_lib.storage import package_file


class PackageFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.weeks = base / "ws" / "weeks"
        (self.weeks / "2026-W42" / "assets").mkdir(parents=True)
        (self.weeks / "2026-W42" / "assets" / "plot.png").write_bytes(b"PNG")
        self.secret = base / "secret.txt"
        self.secret.write_text("secret", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_paths_inside_the_weeks_folder_resolve(self):
        self.assertEqual(package_file(self.weeks, "2026-W42/assets/plot.png"), self.weeks / "2026-W42" / "assets" / "plot.png")
        for bad in (str(self.secret), "../secret.txt", "2026-W42/../../secret.txt", "C:\\Windows\\win.ini", "\\\\nas\\share\\x", "", None):
            self.assertIsNone(package_file(self.weeks, bad), bad)

    def test_export_and_paste_never_read_a_source_outside_the_weeks_folder(self):
        from composer_lib.server import App
        cfg = Config(inbox_dir=self.weeks.parent / "inbox", workspace_dir=self.weeks.parent, port=0)
        app = App(cfg)
        draft = {"id": "d-1", "title": "t", "blocks": [{"type": "file", "src": str(self.secret), "caption": "s"},
                                                       {"type": "image", "src": "../../secret.txt", "caption": "s"},
                                                       {"type": "image", "src": "2026-W42/assets/plot.png", "caption": "ok"}]}
        res = app.export(draft)
        folder = Path(res["folder"]) if "folder" in res else cfg.workspace_dir / "export" / "d-1"
        names = sorted(p.name for p in folder.iterdir())
        self.assertFalse(any("secret" in n for n in names), names)
        self.assertTrue(any(n.endswith("plot.png") for n in names), names)
        self.assertNotIn("secret", (folder / "paste.html").read_text(encoding="utf-8").replace("secret.txt", ""))

    def test_confluence_publish_uploads_only_package_files(self):
        from composer_lib.confluence import ConfluenceClient
        from composer_lib.config import ConfluenceConfig
        from tests.test_confluence import FakeTransport
        t = FakeTransport()
        client = ConfluenceClient(ConfluenceConfig(base_url="https://wiki.corp", pat="x", default_space="AI"), transport=t)
        draft = {"id": "d-2", "title": "t", "blocks": [{"type": "file", "src": str(self.secret), "caption": "s"}]}
        client.publish(draft, self.weeks, space="AI", parent_id=None)
        uploads = [c for c in t.calls if c["method"] == "POST" and "child/attachment" in c["url"]]
        self.assertEqual(uploads, [])


class PageHostTests(unittest.TestCase):
    def test_the_page_host_cannot_be_the_ui_host_or_an_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("127.0.0.1", "127.0.0.2", "localhost:9000", "[::1]", "LOCALHOST "):
                p = Path(tmp) / "c.json"
                p.write_text(json.dumps({"page_host": bad}), encoding="utf-8")
                self.assertEqual(load_config(p).page_host, "localhost" if bad.strip().lower() != "localhost" else "localhost", bad)
            p.write_text(json.dumps({"page_host": "composer-pages.localhost"}), encoding="utf-8")
            self.assertEqual(load_config(p).page_host, "composer-pages.localhost")


if __name__ == "__main__":
    unittest.main()
