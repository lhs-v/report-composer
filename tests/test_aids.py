import unittest
from composer_lib.aids import KINDS, build, numbers_in_source, parse
from tests.test_outline import tree_draft, P


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.d = tree_draft()
        self.claim = next(n for n in self.d["nodes"].values() if n["kind"] == "claim" and n["src"]["chapter"] == "C-U-1")
        self.rec = next(n for n in self.d["nodes"].values() if n["kind"] == "record" and n["src"]["record"] == "R-new")

    def test_node_prompt_carries_title_body_and_on_children_only(self):
        off = next(n for n in self.d["nodes"].values() if n["src"].get("record") == "R-old")
        b = build("node", self.d, self.claim["id"])
        self.assertEqual(b["target"], {"id": self.claim["id"], "field": "text"})
        self.assertIn("비교 결론", b["prompt"]); self.assertIn("리드.", b["prompt"]); self.assertIn("무엇", b["prompt"])   # R-new caption
        self.assertNotIn(off["title"], b["prompt"])                                                                   # R-old is off
        self.assertNotIn("records/", b["prompt"])                                                                     # no paths
        self.assertIn("개조식", b["prompt"])

    def test_summary_prompt_uses_on_claims_and_decisions_and_targets_the_summary_node(self):
        b = build("summary", self.d, None)
        self.assertEqual(b["target"]["field"], "text")
        self.assertEqual(self.d["nodes"][b["target"]["id"]]["kind"], "summary")
        self.assertIn("sp-mobile", b["prompt"]); self.assertIn("결정 하나", b["prompt"]); self.assertNotIn("생략할 것", b["prompt"])

    def test_caption_prompt_targets_the_caption_field(self):
        b = build("caption", self.d, self.rec["id"])
        self.assertEqual(b["target"], {"id": self.rec["id"], "field": "caption"})
        self.assertIn("새 페이지", b["prompt"]); self.assertIn("비교 결론", b["prompt"])
        self.assertEqual(b["before"], ["무엇", "왜"])

    def test_ledger_items_are_shown_with_their_korean_labels(self):
        proj = next(n for n in self.d["nodes"].values() if n["kind"] == "project")
        prompt = build("node", self.d, proj["id"])["prompt"]
        self.assertIn("- 결정: 결정 하나", prompt); self.assertIn("- 열림: 열린 것", prompt)
        self.assertNotIn("decision", prompt); self.assertNotIn("open:", prompt)

    def test_unknown_kind_or_wrong_node_kind_raises(self):
        with self.assertRaises(ValueError):
            build("node", self.d, self.rec["id"])          # a record has no body to rewrite
        with self.assertRaises(ValueError):
            build("poem", self.d, None)


class ParseTests(unittest.TestCase):
    def test_numbers_guard(self):
        self.assertTrue(numbers_in_source("정확도 92%", "원문 92% 였다"))
        self.assertFalse(numbers_in_source("정확도 93%", "원문 92% 였다"))

    def test_node_answer_is_unfenced_and_guarded(self):
        self.assertEqual(parse("node", "```md\n다듬은 본문\n```", "원문")["value"], "다듬은 본문")
        r = parse("node", "97% 달성", "원문 92%")
        self.assertFalse(r["ok"]); self.assertIn("97", r["reason"])

    def test_windows_line_endings_are_normalised(self):
        self.assertEqual(parse("node", "첫 줄\r\n둘째 줄\r\n", "")["value"], "첫 줄\n둘째 줄")
        self.assertEqual(parse("node", "```md\r\n다듬은 본문\r\n```\r\n", "")["value"], "다듬은 본문")
        self.assertEqual(parse("summary", "a: 하나\r\nb: 둘", "")["value"], ["a: 하나", "b: 둘"])

    def test_summary_is_at_most_five_lines_and_caption_two(self):
        s = parse("summary", "\n".join(f"- a: {i}" for i in range(1, 8)), "1 2 3 4 5 6 7")
        self.assertEqual(len(s["value"]), 5)
        c = parse("caption", "- 무엇이 보이나\n- 왜 중요한가\n- 셋째", "")
        self.assertEqual(c["value"], ["무엇이 보이나", "왜 중요한가"])
