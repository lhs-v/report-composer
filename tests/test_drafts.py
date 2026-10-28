import tempfile
import unittest
from pathlib import Path

from composer_lib.drafts import Drafts


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.drafts = Drafts(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_list_save_get_roundtrip(self):
        d = self.drafts.create("10월 둘째 주 보고")
        self.assertTrue(d["id"].startswith("d-"))
        self.assertEqual([x["title"] for x in self.drafts.list()], ["10월 둘째 주 보고"])
        d["blocks"] = [{"id": "b1", "type": "heading", "level": 2, "text": "제목", "source_ref": "2026-W42:alpha:0:heading:0"},
                       {"id": "b2", "type": "image", "src": "2026-W42/pages/alpha-01/preview.png", "caption": "캡처", "source_ref": None}]
        saved = self.drafts.save(d)
        self.assertGreaterEqual(saved["updated"], d["created"])
        got = self.drafts.get(d["id"])
        self.assertEqual([b["type"] for b in got["blocks"]], ["heading", "image"])
        self.assertEqual(self.drafts.list()[0]["block_count"], 2)

    def test_duplicate_copies_blocks_and_clears_confluence_binding(self):
        d = self.drafts.create("원본")
        d["blocks"] = [{"id": "b1", "type": "paragraph", "text": "p", "source_ref": None}]
        d["confluence"] = {"page_id": "100", "version": 3, "url": "https://wiki/x"}
        self.drafts.save(d)
        c = self.drafts.duplicate(d["id"])
        self.assertNotEqual(c["id"], d["id"])
        self.assertEqual(c["title"], "원본 (복사본)")
        self.assertEqual(c["blocks"][0]["text"], "p")
        self.assertIsNone(c["confluence"])

    def test_invalid_block_type_is_rejected_and_delete_removes_file(self):
        d = self.drafts.create("x")
        d["blocks"] = [{"id": "b1", "type": "table", "rows": [["a"]]}]
        self.drafts.save(d)                                   # table is a real block type now
        d["blocks"] = [{"id": "b1", "type": "spreadsheet", "text": "?"}]
        with self.assertRaises(ValueError):
            self.drafts.save(d)
        self.drafts.delete(d["id"])
        self.assertIsNone(self.drafts.get(d["id"]))
        self.assertEqual(self.drafts.list(), [])

    def test_tree_drafts_are_validated_and_listed_with_their_kind(self):
        tree = {"nodes": {"n-a": {"id": "n-a", "kind": "summary", "title": "요약", "text": "x", "on": True, "folded": False, "page": False, "stale": False,
                                  "src": {"week": "2026-W43", "project": None, "chapter": None, "record": None}, "marks": [], "tier": "main", "children": []}},
                "root": ["n-a"], "round": 1}
        d = self.drafts.create_tree("트리 초안", "2026-W43", tree)
        self.assertEqual((d["kind"], d["week"], d["root"]), ("tree", "2026-W43", ["n-a"]))
        self.assertEqual(self.drafts.list()[0]["kind"], "tree")
        d["nodes"]["n-a"]["children"] = ["n-missing"]
        with self.assertRaises(ValueError):
            self.drafts.save(d)
        d["nodes"]["n-a"]["children"] = []
        d["nodes"]["n-a"]["kind"] = "banana"
        with self.assertRaises(ValueError):
            self.drafts.save(d)
        d["nodes"]["n-a"]["kind"] = "summary"
        d["root"] = ["n-missing"]
        with self.assertRaises(ValueError):
            self.drafts.save(d)
        self.drafts.create("블록")
        self.assertEqual({"tree", "blocks"}, {x["kind"] for x in self.drafts.list()})


if __name__ == "__main__":
    unittest.main()
