# composer/tests/test_outline.py
import unittest

from composer_lib.outline import build_tree, node_id

P = "C--Claude-sp-mobile"
PKG = {
    "schema": 3, "package_version": 9, "week": "2026-W43", "since": "2026-10-19", "until": "2026-10-25", "round": 2, "mode": "delta",
    "outline": {"summary": ["sp-mobile: 비교 결론을 냄"], "made_by": "claude:sonnet", "made_at": "x"},
    "projects": {P: {"project": P, "mode": "chapters", "overview": "개요 문장.",
        "ledger": {"stage": "단계", "transition": None, "decisions": ["결정 하나"], "open": [{"text": "열린 것", "since": "2026-W42"}], "resolved": [], "next_steps": []},
        "chapters": [
            {"id": "C-U-1", "title": "비교 결론", "lead": "리드.", "tier": "main", "value": "추천", "change": "지난주보다 빨라짐",
             "flow": [{"when": "2026-10-21", "text": "첫 실험"}, {"when": "2026-10-23", "text": "결론"}], "sentences": [], "units": [], "results": []},
            {"id": "C-U-2", "title": "부록 조사", "lead": "조사.", "tier": "appendix", "value": "선택", "change": "", "flow": [{"when": "2026-10-22", "text": "읽음"}], "sentences": [], "units": [], "results": []},
            {"id": "C-U-3", "title": "생략할 것", "lead": "", "tier": "appendix", "value": "생략", "change": "", "flow": [], "sentences": [], "units": [], "results": []}]}},
    "records": [
        {"id": "R-new", "kind": "page", "title": "새 페이지", "summary": "요약", "project": P, "sent": "core", "chapter": "C-U-1", "in_round": True, "caption": ["무엇", "왜"],
         "representative": "records/sp-mobile/R-new/preview-top.png", "href": "records/sp-mobile/R-new/index.html",
         "files": [{"rel": "index.html", "role": "core", "href": "records/sp-mobile/R-new/index.html"}, {"rel": "preview-top.png", "role": "derived", "href": "records/sp-mobile/R-new/preview-top.png"}]},
        {"id": "R-old", "kind": "figure", "title": "지난 회차 그림", "summary": "", "project": P, "sent": "core", "chapter": "C-U-1", "in_round": False,
         "representative": None, "href": "records/sp-mobile/R-old/f.png", "files": [{"rel": "f.png", "role": "core", "href": "records/sp-mobile/R-old/f.png"}]},
        {"id": "R-home", "kind": "video", "title": "집에 남은 영상", "summary": "", "project": P, "sent": "core", "chapter": "C-U-2", "in_round": True,
         "representative": None, "href": None, "files": [{"rel": "v.mp4", "role": "core", "home": True}]},
        {"id": "R-none", "kind": "figure", "title": "숨김", "summary": "", "project": P, "sent": "none", "chapter": None, "in_round": False, "representative": None, "href": None, "files": []}]}


class BuildTreeTests(unittest.TestCase):
    def setUp(self):
        self.t = build_tree(PKG, "2026-W43")
        self.n = self.t["nodes"]

    def by(self, kind, **src):
        return [x for x in self.n.values() if x["kind"] == kind and all(x["src"].get(k) == v for k, v in src.items())]

    def test_root_is_summary_then_projects_and_ids_are_deterministic(self):
        self.assertEqual([self.n[i]["kind"] for i in self.t["root"]], ["summary", "project"])
        self.assertEqual(self.n[self.t["root"][0]]["text"], "sp-mobile: 비교 결론을 냄")
        self.assertEqual(self.t["root"], build_tree(PKG, "2026-W43")["root"])
        self.assertEqual(node_id("2026-W43", P, "C-U-1", None, "claim"), node_id("2026-W43", P, "C-U-1", None, "claim"))
        self.assertNotEqual(node_id("2026-W43", P, "C-U-1", None, "claim"), node_id("2026-W43", P, "C-U-1", None, "flow"))

    def test_claims_follow_tier_and_value(self):
        main, = self.by("claim", chapter="C-U-1")
        app, = self.by("claim", chapter="C-U-2")
        skip, = self.by("claim", chapter="C-U-3")
        self.assertEqual((main["on"], main["folded"]), (True, False))
        self.assertEqual((app["on"], app["folded"]), (True, True))
        self.assertEqual(skip["on"], False)
        self.assertEqual(main["text"], "리드.")
        self.assertIn("changed", main["marks"])

    def test_records_follow_round_and_home(self):
        new, = self.by("record", record="R-new")
        old, = self.by("record", record="R-old")
        home, = self.by("record", record="R-home")
        self.assertEqual((new["on"], new["marks"], new["caption"]), (True, ["new"], ["무엇", "왜"]))
        self.assertEqual((old["on"], old["marks"]), (False, ["sent"]))
        self.assertEqual((home["on"], home["folded"]), (True, True))
        self.assertIn("home", home["marks"])
        self.assertEqual(old["caption"], ["지난 회차 그림"])                  # no seed: rule caption
        self.assertEqual(new["show"], "representative")
        self.assertEqual(self.by("record", record="R-none"), [])             # sent none: not in the tree at all

    def test_flow_and_ledger_nodes(self):
        flow, = self.by("flow", chapter="C-U-1")
        self.assertEqual((flow["on"], flow["folded"], len(flow["items"])), (True, True, 2))
        short, = self.by("flow", chapter="C-U-2")
        self.assertEqual(short["on"], False)                                  # one item only
        ledger, = self.by("ledger", project=P)
        self.assertEqual(ledger["on"], True)
        self.assertEqual(ledger["items"][0], {"kind": "decision", "text": "결정 하나"})

    def test_children_are_claims_then_ledger_and_a_claim_holds_records_then_flow(self):
        proj = self.n[self.t["root"][1]]
        kinds = [self.n[c]["kind"] for c in proj["children"]]
        self.assertEqual(kinds, ["claim", "claim", "claim", "ledger"])
        main, = self.by("claim", chapter="C-U-1")
        self.assertEqual([self.n[c]["kind"] for c in main["children"]], ["record", "record", "flow"])

    def test_memory_marks_used_and_prefers_remembered_captions(self):
        mem = {"captions": {"R-new": {"text": ["내가 고친 것"], "week": "2026-W43"}}, "used": {"R-old": ["2026-W42"], "C-U-1": ["2026-W42"]}}
        t = build_tree(PKG, "2026-W43", mem)
        new = next(x for x in t["nodes"].values() if x["src"].get("record") == "R-new")
        old = next(x for x in t["nodes"].values() if x["src"].get("record") == "R-old")
        main = next(x for x in t["nodes"].values() if x["kind"] == "claim" and x["src"].get("chapter") == "C-U-1")
        self.assertEqual(new["caption"], ["내가 고친 것"])
        self.assertIn("used", old["marks"])
        self.assertIn("used", main["marks"])

    def test_a_package_without_seeds_round_or_ledger_still_builds(self):
        bare = {"schema": 3, "week": "2026-W41", "projects": {P: {"project": P, "overview": "", "chapters": [{"id": "C-1", "title": "T", "lead": "L", "tier": "main", "sentences": [], "units": []}]}},
                "records": [{"id": "R-1", "kind": "figure", "title": "F", "project": P, "sent": "core", "chapter": "C-1", "files": [{"rel": "f.png", "role": "core", "href": "records/sp-mobile/R-1/f.png"}], "href": "records/sp-mobile/R-1/f.png"}]}
        t = build_tree(bare, "2026-W41")
        self.assertEqual(t["round"], 1)
        rec = next(x for x in t["nodes"].values() if x["kind"] == "record")
        self.assertEqual((rec["on"], rec["marks"]), (True, ["new"]))
        self.assertEqual(t["nodes"][t["root"][0]]["text"], "sp-mobile: T")          # rule summary
        self.assertEqual(t["counts"]["stale"], 0)
