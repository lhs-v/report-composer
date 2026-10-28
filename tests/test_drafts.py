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


    def _tree(self):
        node = {"id": "n-a", "kind": "summary", "title": "요약", "text": "x", "on": True, "folded": False, "page": False, "stale": False,
                "src": {"week": "2026-W43", "project": None, "chapter": None, "record": None}, "marks": [], "tier": "main", "children": []}
        return {"nodes": {"n-a": node}, "root": ["n-a"], "round": 1}

    def test_duplicating_a_tree_draft_drops_the_confluence_bindings(self):
        d = self.drafts.create_tree("트리", "2026-W43", self._tree())
        d["pages"] = {"n-a": {"page_id": "1", "version": 1, "url": "https://wiki/x"}}
        d["confluence"] = {"page_id": "9"}
        self.drafts.save(d)
        copy_ = self.drafts.duplicate(d["id"])
        self.assertNotEqual(copy_["id"], d["id"])
        self.assertEqual((copy_["pages"], copy_["confluence"]), ({}, None))
        self.assertEqual((copy_["kind"], copy_["week"], copy_["root"], copy_["nodes"]), ("tree", "2026-W43", ["n-a"], d["nodes"]))
        self.assertEqual(self.drafts.get(d["id"])["pages"], d["pages"])    # the original keeps its own

    def test_saving_without_kind_still_validates_a_stored_tree_draft(self):
        d = self.drafts.create_tree("트리", "2026-W43", self._tree())
        bad = self._tree()
        bad["nodes"]["n-a"]["children"] = ["n-missing"]
        with self.assertRaises(ValueError):
            self.drafts.save({"id": d["id"], "nodes": bad["nodes"], "root": bad["root"]})
        self.assertEqual(self.drafts.get(d["id"])["nodes"]["n-a"]["children"], [])
        self.drafts.save({"id": d["id"], "title": "새 제목"})              # a partial save of a valid tree is fine
        self.assertEqual(self.drafts.get(d["id"])["kind"], "tree")

    def _two_nodes(self):
        t = self._tree()
        t["nodes"]["n-b"] = {**t["nodes"]["n-a"], "id": "n-b", "kind": "project", "children": []}
        t["nodes"]["n-a"]["children"] = ["n-b"]
        return t

    def test_a_child_listed_twice_is_rejected(self):
        t = self._two_nodes()
        self.drafts.create_tree("트리", "2026-W43", t)                                    # n-a > n-b is fine
        dup = self._two_nodes()
        dup["nodes"]["n-a"]["children"] = ["n-b", "n-b"]                                  # twice under one parent
        with self.assertRaises(ValueError):
            self.drafts.create_tree("트리", "2026-W43", dup)
        both = self._two_nodes()
        both["root"] = ["n-a", "n-b"]                                                     # under n-a and at the top level
        with self.assertRaises(ValueError):
            self.drafts.create_tree("트리", "2026-W43", both)

    def test_a_children_cycle_is_rejected(self):
        t = self._two_nodes()
        t["nodes"]["n-b"]["children"] = ["n-a"]                                           # n-a > n-b > n-a
        with self.assertRaises(ValueError):
            self.drafts.create_tree("트리", "2026-W43", t)
        d = self.drafts.create_tree("트리", "2026-W43", self._two_nodes())
        with self.assertRaises(ValueError):
            self.drafts.save({"id": d["id"], "nodes": t["nodes"]})
        self.assertEqual(self.drafts.get(d["id"])["nodes"]["n-b"]["children"], [])


if __name__ == "__main__":
    unittest.main()
