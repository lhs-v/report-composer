import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.config import ConfluenceConfig
from composer_lib.confluence import ConfluenceClient, ConfluenceError


class FakeTransport:
    """Records every call; answers from a small script keyed by (method, path prefix)."""

    def __init__(self, fail_status=None):
        self.calls = []
        self.fail_status = fail_status
        self.page_version = 1
        self.attachments = {}

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        path = url.split("/rest/api/", 1)[1]
        if self.fail_status:
            return self.fail_status, {}, json.dumps({"statusCode": self.fail_status, "message": "권한이 없습니다"}).encode()
        if method == "POST" and path == "content":
            return 200, {}, json.dumps({"id": "900", "version": {"number": 1}, "_links": {"webui": "/pages/viewpage.action?pageId=900"}}).encode()
        if method == "GET" and path.startswith("content/900?"):
            return 200, {}, json.dumps({"id": "900", "title": "t", "version": {"number": self.page_version}, "space": {"key": "AI"},
                                        "_links": {"webui": "/pages/viewpage.action?pageId=900"}}).encode()
        if method == "GET" and path.startswith("content/900/child/attachment"):
            return 200, {}, json.dumps({"results": [{"id": aid, "title": name} for name, aid in self.attachments.items()]}).encode()
        if method == "POST" and path.startswith("content/900/child/attachment"):
            name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            aid = self.attachments.setdefault(name, f"att-{len(self.attachments) + 1}")
            return 200, {}, json.dumps({"results": [{"id": aid, "title": name}]}).encode()
        if method == "PUT" and path == "content/900":
            self.page_version = json.loads(body)["version"]["number"]
            return 200, {}, json.dumps({"id": "900", "version": {"number": self.page_version}, "_links": {"webui": "/pages/viewpage.action?pageId=900"}}).encode()
        if method == "GET" and path.startswith("space"):
            return 200, {}, json.dumps({"results": [{"key": "AI", "name": "AI Lab"}]}).encode()
        if method == "GET" and path.startswith("content/search"):
            return 200, {}, json.dumps({"results": [{"id": "77", "title": "주간 성과 보고"}]}).encode()
        return 404, {}, b"{}"


CFG = ConfluenceConfig(base_url="https://wiki.corp", pat="secret", default_space="AI", default_parent_id="77")
BLOCKS = [{"id": "1", "type": "heading", "level": 2, "text": "제목"},
          {"id": "2", "type": "image", "src": "2026-W42/pages/alpha-01/preview.png", "caption": "캡처"},
          {"id": "3", "type": "file", "src": "2026-W42/pages/alpha-01/media/v.mp4", "caption": "영상"}]


class ConfluenceClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.weeks = Path(self.tmp.name)
        (self.weeks / "2026-W42" / "pages" / "alpha-01" / "media").mkdir(parents=True)
        (self.weeks / "2026-W42" / "pages" / "alpha-01" / "preview.png").write_bytes(b"PNG")
        (self.weeks / "2026-W42" / "pages" / "alpha-01" / "media" / "v.mp4").write_bytes(b"MP4")
        self.t = FakeTransport()
        self.client = ConfluenceClient(CFG, transport=self.t)

    def tearDown(self):
        self.tmp.cleanup()

    def test_publish_new_draft_creates_uploads_then_updates_body(self):
        draft = {"id": "d-1", "title": "주간 성과 W42", "blocks": BLOCKS, "confluence": None}
        result = self.client.publish(draft, self.weeks, space="AI", parent_id="77")
        seq = [(c["method"], c["url"].split("/rest/api/", 1)[1].split("?")[0]) for c in self.t.calls]
        self.assertEqual(seq[0], ("POST", "content"))
        self.assertEqual(seq[1], ("GET", "content/900/child/attachment"))            # existing attachments looked up first
        self.assertEqual(seq[2:4], [("POST", "content/900/child/attachment")] * 2)
        self.assertEqual(seq[-1], ("PUT", "content/900"))
        create = json.loads(self.t.calls[0]["body"])
        self.assertEqual((create["space"]["key"], create["ancestors"][0]["id"], create["title"]), ("AI", "77", "주간 성과 W42"))
        upload = self.t.calls[2]
        self.assertEqual(upload["headers"]["X-Atlassian-Token"], "nocheck")
        self.assertIn(b'filename="2026-W42_pages_alpha-01_preview.png"', upload["body"])
        self.assertIn(b"PNG", upload["body"])
        update = json.loads(self.t.calls[-1]["body"])
        self.assertEqual(update["version"]["number"], 2)
        self.assertIn('ri:filename="2026-W42_pages_alpha-01_preview.png"', update["body"]["storage"]["value"])
        self.assertTrue(all(c["headers"]["Authorization"] == "Bearer secret" for c in self.t.calls))
        self.assertEqual((result["page_id"], result["version"]), ("900", 2))
        self.assertEqual(result["url"], "https://wiki.corp/pages/viewpage.action?pageId=900")

    def test_publish_existing_draft_updates_in_place_and_replaces_attachments(self):
        self.t.attachments["2026-W42_pages_alpha-01_preview.png"] = "att-9"
        draft = {"id": "d-1", "title": "주간 성과 W42", "blocks": BLOCKS, "confluence": {"page_id": "900", "version": 1}}
        self.t.page_version = 4
        result = self.client.publish(draft, self.weeks, space="AI", parent_id="77")
        methods = [(c["method"], c["url"].split("/rest/api/", 1)[1].split("?")[0]) for c in self.t.calls]
        self.assertNotIn(("POST", "content"), methods)
        self.assertIn(("POST", "content/900/child/attachment/att-9/data"), methods)   # existing file is replaced
        self.assertEqual(json.loads(self.t.calls[-1]["body"])["version"]["number"], 5)
        self.assertEqual(result["version"], 5)

    def test_errors_carry_the_server_message(self):
        client = ConfluenceClient(CFG, transport=FakeTransport(fail_status=403))
        with self.assertRaises(ConfluenceError) as ctx:
            client.spaces()
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("권한이 없습니다", str(ctx.exception))

    def test_space_and_page_search_helpers(self):
        self.assertEqual(self.client.spaces(), [{"key": "AI", "name": "AI Lab"}])
        self.assertEqual(self.client.search_pages("AI", "주간"), [{"id": "77", "title": "주간 성과 보고"}])
        q = self.t.calls[-1]["url"]
        self.assertIn("cql=", q)
        self.assertIn("%22AI%22", q)

    def test_pat_never_appears_in_repr_or_errors(self):
        self.assertNotIn("secret", repr(self.client))
        client = ConfluenceClient(CFG, transport=FakeTransport(fail_status=500))
        try:
            client.spaces()
        except ConfluenceError as e:
            self.assertNotIn("secret", str(e))

    def test_cloud_uses_basic_auth_with_email_when_email_is_configured(self):
        import base64
        cfg = ConfluenceConfig(base_url="https://corp.atlassian.net/wiki", pat="apitoken", email="me@corp.com", default_space="SODA")
        t = FakeTransport()
        ConfluenceClient(cfg, transport=t).spaces()
        expected = "Basic " + base64.b64encode(b"me@corp.com:apitoken").decode()
        self.assertEqual(t.calls[0]["headers"]["Authorization"], expected)
        self.assertTrue(t.calls[0]["url"].startswith("https://corp.atlassian.net/wiki/rest/api/space"))
        self.assertNotIn("apitoken", repr(ConfluenceClient(cfg, transport=t)))


if __name__ == "__main__":
    unittest.main()
