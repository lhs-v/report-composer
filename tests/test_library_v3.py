"""Package format v3 (records): a card per record, read from `records`; records whose folder has not arrived yet are
named, files that stayed home are named, and the v2 chapters still frame the page."""
import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.library import build_library, find_block

WEEK = "2026-W43"
C1 = "C-U-e980fb09-10211943"
P = "C--Claude-sp-mobile"
R_PAGE, R_FIG, R_VID, R_HIDDEN, R_LATE = "R-aPAGE1", "R-fFIG1", "R-fVID1", "R-fHID1", "R-fLATE1"


def rec(rid, kind, title, files, chapter=None, sent="core", why="추론", video=None, representative=None, href=None):
    return {"id": rid, "kind": kind, "title": title, "summary": "요약 " + title, "project": P, "when": "2026-10-21T01:00:00+00:00",
            "source": "inferred", "sent": sent, "why": why, "video": video, "chapter": chapter, "representative": representative,
            "href": href, "files": files, "bytes": sum(f["bytes"] for f in files if f.get("href")), "home_bytes": sum(f["bytes"] for f in files if f.get("home"))}


def f(rel, role, n, rid=None, home=False):
    base = {"rel": rel, "role": role, "bytes": n}
    return {**base, "home": True} if home else {**base, "href": f"records/sp-mobile/{rid}/{rel}"}


OUTCOMES_V3 = {
    "schema": 3, "package_version": 8, "week": WEEK, "since": "2026-10-19", "until": "2026-10-25", "scope": ["sp-mobile"],
    "projects": {P: {
        "project": P, "mode": "chapters", "overview": "개요 문장", "one_line": "",
        "chapters": [{"id": C1, "tier": "main", "value": "추천", "kind": "결과", "section": "결과", "title": "등급 체계 결론", "label": "G",
                      "lead": "리드.", "anchor": {"unit": "U-1", "text": ""}, "sentences": [{"unit": "U-1", "text": "한 일."}],
                      "units": [{"id": "U-1", "when": "2026-10-21 10:00", "role": "member", "link": "hard", "line": "한 줄"}],
                      "results": ["E-aPAGE1", "E-tU-1"], "change": "", "md": "sp-mobile-01-G.md"}],
        "evidence": [{"n": 1, "eid": "E-aPAGE1", "kind": "artifact", "unit": "U-1", "units": ["U-1"], "title": "등급 영상 페이지", "path": "index.html",
                      "when": "2026-10-21T01:00:00+00:00", "files": [["a.png", "a.png"]],
                      "package": {"href": f"records/sp-mobile/{R_PAGE}/index.html", "thumb": f"records/sp-mobile/{R_PAGE}/preview-top.png",
                                  "files": [f"records/sp-mobile/{R_PAGE}/a.png"]}},
                     {"n": 2, "eid": "E-tU-1", "kind": "text", "unit": "U-1", "title": "응답 발췌", "package": {"href": "texts/U-1.md"}}],
        "units": [{"id": "U-1", "when": "2026-10-21 10:00", "line": "한 줄", "chapter": C1}], "warnings": [], "error": None}},
    "records": [
        rec(R_PAGE, "page", "등급 영상 페이지", [f("index.html", "core", 1000, R_PAGE), f("a.png", "support", 500, R_PAGE),
                                                f("b.mp4", "support", 5000, home=True), f("preview-top.png", "derived", 200, R_PAGE)],
            chapter=C1, why="정리 단위 인용", representative=f"records/sp-mobile/{R_PAGE}/preview-top.png", href=f"records/sp-mobile/{R_PAGE}/index.html"),
        rec(R_FIG, "figure", "결과 그림", [f("fig.png", "core", 300, R_FIG)], href=f"records/sp-mobile/{R_FIG}/fig.png",
            representative=f"records/sp-mobile/{R_FIG}/fig.png"),
        rec(R_VID, "video", "시연 영상", [f("v.mp4", "core", 4000, home=True), f("v.poster.jpg", "derived", 100, R_VID), f("v.720p.mp4", "derived", 800, R_VID)],
            video="720p", representative=f"records/sp-mobile/{R_VID}/v.poster.jpg", href=f"records/sp-mobile/{R_VID}/v.720p.mp4"),
        rec(R_HIDDEN, "doc", "숨긴 문서", [f("h.md", "core", 10, home=True)], sent="none", why="숨김"),
        rec(R_LATE, "doc", "아직 안 온 문서", [f("late.md", "core", 10, R_LATE)], href=f"records/sp-mobile/{R_LATE}/late.md"),
    ],
}


class V3Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.weeks = Path(self.tmp.name) / "weeks"
        self.week_dir = self.weeks / WEEK
        self.week_dir.mkdir(parents=True)
        (self.week_dir / "outcomes.json").write_text(json.dumps(OUTCOMES_V3, ensure_ascii=False), encoding="utf-8")
        (self.week_dir / "sp-mobile-01-G.md").write_text("# 등급 체계 결론", encoding="utf-8")
        (self.week_dir / "texts").mkdir()
        (self.week_dir / "texts" / "U-1.md").write_text("# 응답 발췌\n\n본문", encoding="utf-8")
        for r in OUTCOMES_V3["records"]:
            if r["id"] == R_LATE:
                continue                                       # its part has not arrived
            for fl in r["files"]:
                if fl.get("href"):
                    p = self.week_dir / fl["href"]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"0" * fl["bytes"])

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self):
        return build_library(self.weeks)[0]

    def project(self):
        return self.entry()["projects"][0]


class V3Tests(V3Fixture):
    def test_the_week_is_read_as_format_3_without_a_warning(self):
        e = self.entry()
        self.assertEqual(e["schema"], 3)
        self.assertNotIn("warning", e)
        self.assertEqual(self.project()["schema"], 3)
        self.assertEqual(self.project()["mode"], "chapters")

    def test_a_cited_record_is_the_chapters_result_with_record_based_ids(self):
        s = self.project()["streams"][0]
        ids = [b["id"] for b in s["blocks"]]
        self.assertIn(f"{WEEK}:sp-mobile:{C1}:heading:0", ids)
        self.assertIn(f"{WEEK}:sp-mobile:{C1}:{R_PAGE}:image:0", ids)              # the first screen, from the record
        self.assertIn(f"{WEEK}:sp-mobile:{C1}:{R_PAGE}:page:0", ids)
        self.assertIn(f"{WEEK}:sp-mobile:{C1}:{R_PAGE}:image:1", ids)              # a.png travelled with the page
        self.assertIn(f"{WEEK}:sp-mobile:{C1}:text:1", ids)                        # the excerpt keeps its v2 id
        self.assertNotIn("b.mp4", json.dumps(s["blocks"]))                          # stayed home: not a block
        page = next(b for b in s["blocks"] if b["id"].endswith(f"{R_PAGE}:page:0"))
        self.assertEqual(page["src"], f"{WEEK}/records/sp-mobile/{R_PAGE}/index.html")
        self.assertEqual(page["record"], R_PAGE)
        a = next(b for b in s["blocks"] if b["id"].endswith(f"{R_PAGE}:image:1"))
        self.assertTrue(a["in_page"])
        self.assertEqual(s["home"], [{"record": R_PAGE, "title": "등급 영상 페이지", "files": ["b.mp4"], "bytes": 5000}])

    def test_records_no_chapter_cites_are_loose_blocks_with_their_record_in_the_id(self):
        p = self.project()
        loose = [b for b in p["blocks"] if not b.get("role")]
        ids = {b["id"] for b in loose}
        self.assertIn(f"{WEEK}:sp-mobile:loose:{R_FIG}:image:0", ids)
        self.assertIn(f"{WEEK}:sp-mobile:loose:{R_VID}:image:0", ids)              # the poster
        self.assertIn(f"{WEEK}:sp-mobile:loose:{R_VID}:file:0", ids)               # the 720p copy is the file to open
        self.assertNotIn(R_HIDDEN, json.dumps(loose))                               # sent: none → nothing to pick
        vid = next(b for b in loose if b["id"].endswith(f"{R_VID}:file:0"))
        self.assertEqual(vid["src"], f"{WEEK}/records/sp-mobile/{R_VID}/v.720p.mp4")

    def test_the_project_lists_its_records_and_says_which_have_not_arrived(self):
        p = self.project()
        by = {r["id"]: r for r in p["records"]}
        self.assertEqual(sorted(by), [R_PAGE, R_FIG, R_HIDDEN, R_LATE, R_VID])
        self.assertTrue(by[R_PAGE]["arrived"])
        self.assertEqual(by[R_PAGE]["chapter"], C1)
        self.assertFalse(by[R_LATE]["arrived"])                                     # listed, with no folder yet
        self.assertEqual(by[R_LATE]["title"], "아직 안 온 문서")
        self.assertEqual(by[R_HIDDEN]["sent"], "none")
        self.assertEqual(by[R_PAGE]["home"], ["b.mp4"])
        self.assertEqual(self.entry()["missing"], [{"project": "sp-mobile", "id": R_LATE, "title": "아직 안 온 문서"}])
        self.assertEqual(find_block(self.weeks, f"{WEEK}:sp-mobile:{C1}:{R_PAGE}:page:0")["record"], R_PAGE)

    def test_ids_are_stable_when_a_record_is_missing(self):
        before = {b["id"] for s in self.project()["streams"] for b in s["blocks"]} | {b["id"] for b in self.project()["blocks"]}
        import shutil
        shutil.rmtree(self.week_dir / "records" / "sp-mobile" / R_FIG)                # that part never came
        after = {b["id"] for s in self.project()["streams"] for b in s["blocks"]} | {b["id"] for b in self.project()["blocks"]}
        self.assertEqual(before - after, {f"{WEEK}:sp-mobile:loose:{R_FIG}:image:0"})
        self.assertIn(R_FIG, [m["id"] for m in self.entry()["missing"]])

    def test_a_week_before_its_weekly_run_shows_the_records_under_the_one_line(self):
        data = json.loads(json.dumps(OUTCOMES_V3))
        data["projects"][P].update({"mode": "one_line", "one_line": "정리 단위 전: 결과물 5개", "chapters": [], "evidence": [], "units": []})
        for r in data["records"]:
            r["chapter"] = None
        (self.week_dir / "outcomes.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        p = self.project()
        self.assertEqual(p["mode"], "one_line")
        ids = {b["id"] for b in p["blocks"]}
        self.assertIn(f"{WEEK}:sp-mobile:one_line:paragraph:0", ids)
        self.assertIn(f"{WEEK}:sp-mobile:loose:{R_PAGE}:page:0", ids)
        self.assertEqual(len(p["records"]), 5)


if __name__ == "__main__":
    unittest.main()
