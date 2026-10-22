"""Package format v2 (chapters): one library stream per chapter, results found only through evidence[].package."""
import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.library import build_library, find_block

WEEK = "2026-W43"
C1 = "C-U-a43e2f42-10131823"
C2 = "C-U-b0000001-10150900"
C3 = "C-U-c0000002-10161000"

OUTCOMES_V2 = {
    "schema": 2,
    "week": WEEK, "since": "2026-10-19", "until": "2026-10-25",
    "scope": ["alpha", "beta", "gamma"],
    "projects": {
        "C--Claude-alpha": {
            "project": "C--Claude-alpha",
            "mode": "chapters",
            "overview": "F5 결론과 받아쓰기 도구 정리",
            "one_line": "",
            "chapters": [
                {
                    "id": C1, "tier": "main", "value": "추천", "kind": "결과", "section": "결과",
                    "title": "F5 실험 결론", "label": "F5",
                    "lead": "폰에 올릴 위치별 활동 판단 방법은 아직 없다.",
                    "anchor": {"unit": "U-a43e2f42-10131823", "text": "끊은 계기"},
                    "sentences": [
                        {"unit": "U-a43e2f42-10131823", "text": "세 위치에서 받아쓰기 정확도를 비교했다."},
                        {"unit": "U-a43e2f42-10141010", "text": "주머니 위치만 기준을 넘지 못했다."},
                    ],
                    "units": [
                        {"id": "U-a43e2f42-10131823", "when": "2026-10-13 18:23", "role": "member", "link": "hard", "line": "비교 실험 설계"},
                        {"id": "U-a43e2f42-10141010", "when": "2026-10-14 10:10", "role": "evidence", "link": "follow", "line": "비교 페이지 발행"},
                    ],
                    "results": ["E-aPAGE1", "E-tU-a43e2f42-10131823", "E-cU-a43e2f42-10131823-1", "E-fCHECKED", "E-aGONE"],
                    "change": "지난주 가설을 접었다.",
                    "export": "ok",
                },
                {
                    "id": C2, "tier": "appendix", "value": "선택", "kind": "데이터·도구", "section": "도구",
                    "title": "받아쓰기 비교 도구", "label": "도구",
                    "lead": "", "sentences": [{"unit": "U-b0000001-10150900", "text": "비교 스크립트를 정리했다."}],
                    "units": [], "results": ["E-fREPORT"], "change": "", "export": "ok",
                },
            ],
            "evidence": [
                {"n": 3, "eid": "E-aPAGE1", "kind": "artifact", "unit": "U-a43e2f42-10141010", "title": "F5 받아쓰기 비교 페이지",
                 "url": "https://claude.ai/artifact/PAGE1", "path": None, "when": "2026-10-14T01:59:00+00:00",
                 "files": [["audio/a.mp3", "C:/x/audio/a.mp3"]], "export": "ok",
                 # the folder name deliberately does not follow any `<short>-<nn>` convention
                 "package": {"href": "pages/zz-unrelated-name/index.html", "preview": "pages/zz-unrelated-name/preview.png",
                             "files": ["pages/zz-unrelated-name/audio/a.mp3"]}},
                {"n": 10, "eid": "E-tU-a43e2f42-10131823", "kind": "text", "unit": "U-a43e2f42-10131823",
                 "title": "응답 발췌: F5 판정", "export": "ok", "package": {"href": "texts/U-a43e2f42-10131823.md"}},
                {"n": 11, "eid": "E-cU-a43e2f42-10131823-1", "kind": "commit", "unit": "U-a43e2f42-10131823",
                 "title": "커밋: 비교 스크립트", "export": "ok"},
                {"n": 12, "eid": "E-fCHECKED", "kind": "file", "unit": "U-a43e2f42-10131823", "title": "확인 필요 파일", "export": "check"},
                {"n": 13, "eid": "E-aGONE", "kind": "artifact", "unit": "U-a43e2f42-10131823", "title": "사본이 없는 페이지",
                 "export": "ok", "package": {"href": "pages/missing/index.html", "preview": "pages/missing/preview.png"}},
                {"n": 14, "eid": "E-fREPORT", "kind": "file", "unit": "U-b0000001-10150900", "title": "비교 결과 표",
                 "export": "ok", "package": {"href": "assets/report.csv"}},
            ],
            "units": [{"id": "U-a43e2f42-10131823", "when": "2026-10-13 18:23", "line": "비교 실험 설계", "chapter": C1}],
            "warnings": [], "error": None,
        },
        "C--Claude-beta": {
            "project": "C--Claude-beta", "mode": "daily_list", "overview": "", "one_line": "", "chapters": [], "evidence": [],
            "units": [
                {"id": "U-beta0001-10200900", "when": "2026-10-20 09:00", "line": "로그 정리", "chapter": None},
                {"id": "U-beta0002-10211400", "when": "2026-10-21 14:00", "line": "설정 파일 손질", "chapter": None},
            ],
            "warnings": [], "error": None,
        },
        "C--Claude-gamma": {
            "project": "C--Claude-gamma", "mode": "one_line", "overview": "", "one_line": "자잘한 설정만 손봤다.",
            "chapters": [], "evidence": [], "units": [], "warnings": [], "error": None,
        },
    },
}


def write_v2_package(weeks: Path) -> Path:
    w = weeks / WEEK
    page = w / "pages" / "zz-unrelated-name"
    (page / "audio").mkdir(parents=True)
    (w / "texts").mkdir()
    (w / "assets").mkdir()
    (w / "outcomes.json").write_text(json.dumps(OUTCOMES_V2, ensure_ascii=False), encoding="utf-8")
    (page / "index.html").write_text("<title>F5</title><h2>비교</h2>", encoding="utf-8")
    (page / "preview.png").write_bytes(b"PNG")
    (page / "audio" / "a.mp3").write_bytes(b"0" * 1500)
    (page / "audio" / "unlisted.mp3").write_bytes(b"0")          # not in package.files: must not appear
    (w / "texts" / "U-a43e2f42-10131823.md").write_text("# F5 판정\n주머니 위치는 탈락.", encoding="utf-8")
    (w / "assets" / "report.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (w / "alpha-01-f5.md").write_text("# F5 실험 결론\n본문", encoding="utf-8")
    (w / "alpha-02-tool.md").write_text("# 받아쓰기 비교 도구\n본문", encoding="utf-8")
    (w / "weekly.md").write_text("# 주간 개요 W43", encoding="utf-8")
    (w / "README.md").write_text("# 패키지 안내", encoding="utf-8")
    (w / "outcomes.html").write_text("<p>cards</p>", encoding="utf-8")
    return w


class LibraryV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.weeks = Path(self.tmp.name) / "weeks"
        write_v2_package(self.weeks)
        self.lib = build_library(self.weeks)
        self.week = self.lib[0]
        self.projects = {p["short"]: p for p in self.week["projects"]}

    def tearDown(self):
        self.tmp.cleanup()

    def chapter(self, cid=C1):
        return next(s for s in self.projects["alpha"]["streams"] if s["chapter"] == cid)

    def test_week_and_project_metadata(self):
        self.assertEqual(self.week["schema"], 2)
        self.assertEqual((self.week["since"], self.week["until"]), ("2026-10-19", "2026-10-25"))
        alpha = self.projects["alpha"]
        self.assertEqual((alpha["mode"], alpha["overview"]), ("chapters", "F5 결론과 받아쓰기 도구 정리"))
        self.assertEqual([s["id"] for s in alpha["streams"]], [f"{WEEK}:alpha:{C1}", f"{WEEK}:alpha:{C2}"])

    def test_one_stream_per_chapter_with_chapter_metadata(self):
        s = self.chapter()
        self.assertEqual(s["title"], "F5 실험 결론")
        self.assertEqual((s["kind"], s["value"], s["tier"], s["section"]), ("결과", "추천", "main", "결과"))
        self.assertEqual(s["lead"], "폰에 올릴 위치별 활동 판단 방법은 아직 없다.")
        self.assertEqual(s["change"], "지난주 가설을 접었다.")
        self.assertEqual(self.chapter(C2)["tier"], "appendix")

    def test_block_order_and_ids(self):
        blocks = self.chapter()["blocks"]
        self.assertEqual([b["type"] for b in blocks],
                         ["heading", "paragraph", "bullet", "bullet", "image", "page", "file", "markdown", "paragraph", "paragraph", "markdown"])
        self.assertEqual(blocks[0]["id"], f"{WEEK}:alpha:{C1}:heading:0")
        self.assertEqual(blocks[0]["text"], "F5 실험 결론")
        self.assertEqual((blocks[1]["label"], blocks[1]["text"]), ("요약", "폰에 올릴 위치별 활동 판단 방법은 아직 없다."))
        self.assertEqual(blocks[1]["id"], f"{WEEK}:alpha:{C1}:paragraph:0")
        self.assertEqual([(b["text"], b["unit"]) for b in blocks[2:4]],
                         [("세 위치에서 받아쓰기 정확도를 비교했다.", "U-a43e2f42-10131823"), ("주머니 위치만 기준을 넘지 못했다.", "U-a43e2f42-10141010")])
        self.assertEqual(blocks[3]["id"], f"{WEEK}:alpha:{C1}:bullet:1")
        self.assertEqual(len({b["id"] for b in blocks}), len(blocks))
        self.assertTrue(all(b["chapter"] == C1 for b in blocks))

    def test_ids_are_stable_across_two_builds(self):
        first = [b["id"] for p in self.week["projects"] for s in p["streams"] for b in s["blocks"]]
        again = build_library(self.weeks)[0]
        second = [b["id"] for p in again["projects"] for s in p["streams"] for b in s["blocks"]]
        self.assertEqual(first, second)
        self.assertEqual([a["id"] for a in self.week["assets"]], [a["id"] for a in again["assets"]])

    def test_results_resolve_only_through_package_paths(self):
        by_type = {}
        for b in self.chapter()["blocks"]:
            by_type.setdefault(b["type"], []).append(b)
        img, page, f = by_type["image"][0], by_type["page"][0], by_type["file"][0]
        self.assertEqual((img["src"], img["caption"], img["eid"]), (f"{WEEK}/pages/zz-unrelated-name/preview.png", "F5 받아쓰기 비교 페이지", "E-aPAGE1"))
        self.assertEqual(page["src"], f"{WEEK}/pages/zz-unrelated-name/index.html")
        self.assertEqual((f["src"], f["size"]), (f"{WEEK}/pages/zz-unrelated-name/audio/a.mp3", 1500))
        self.assertEqual(len(by_type["file"]), 1)                     # unlisted.mp3 is not in package.files
        text = by_type["markdown"][0]
        self.assertEqual((text["src"], text["eid"], text["caption"]), (f"{WEEK}/texts/U-a43e2f42-10131823.md", "E-tU-a43e2f42-10131823", "응답 발췌: F5 판정"))
        self.assertIn("주머니 위치는 탈락", text["text"])
        eids = {b.get("eid") for b in self.chapter()["blocks"]}
        self.assertFalse(eids & {"E-cU-a43e2f42-10131823-1", "E-fCHECKED", "E-aGONE"})   # no package / no copy on disk
        csv = next(b for b in self.chapter(C2)["blocks"] if b.get("eid") == "E-fREPORT")
        self.assertEqual((csv["type"], csv["src"]), ("file", f"{WEEK}/assets/report.csv"))

    def test_change_and_units_are_optional_and_last_before_chapter_md(self):
        blocks = self.chapter()["blocks"]
        change, units = blocks[-3], blocks[-2]
        self.assertEqual((change["label"], change["text"], change["optional"]), ("지난주 대비", "지난주 가설을 접었다.", True))
        self.assertEqual((units["type"], units["label"], units["optional"]), ("paragraph", "근거 작업 단위", True))
        self.assertEqual(units["text"], "2026-10-13 18:23 · 비교 실험 설계\n2026-10-14 10:10 · 비교 페이지 발행")
        self.assertEqual(sum(1 for b in blocks if b.get("optional")), 2)
        self.assertFalse(any(b.get("optional") for b in self.chapter(C2)["blocks"]))   # empty change, no units
        self.assertNotIn("요약", [b.get("label") for b in self.chapter(C2)["blocks"]])   # empty lead

    def test_chapter_md_files_attach_by_order(self):
        md1 = self.chapter()["blocks"][-1]
        self.assertEqual((md1["type"], md1["src"]), ("markdown", f"{WEEK}/alpha-01-f5.md"))
        md2 = [b["src"] for b in self.chapter(C2)["blocks"] if b["type"] == "markdown"]
        self.assertEqual(md2, [f"{WEEK}/alpha-02-tool.md"])
        srcs = [a["src"] for a in self.week["assets"]]
        self.assertIn(f"{WEEK}/weekly.md", srcs)
        self.assertIn(f"{WEEK}/README.md", srcs)
        self.assertFalse(any("alpha-0" in s for s in srcs))

    def test_one_line_and_daily_list_modes(self):
        gamma = self.projects["gamma"]
        self.assertEqual((gamma["mode"], gamma["streams"], gamma["one_line"]), ("one_line", [], "자잘한 설정만 손봤다."))
        beta = self.projects["beta"]
        self.assertEqual(beta["mode"], "daily_list")
        self.assertEqual(len(beta["streams"]), 1)
        s = beta["streams"][0]
        self.assertEqual(s["title"], "작업 단위 목록")
        self.assertEqual([(b["type"], b["text"], b["unit"]) for b in s["blocks"]],
                         [("bullet", "2026-10-20 09:00 · 로그 정리", "U-beta0001-10200900"),
                          ("bullet", "2026-10-21 14:00 · 설정 파일 손질", "U-beta0002-10211400")])
        self.assertEqual(s["blocks"][1]["id"], f"{WEEK}:beta:units:bullet:1")

    def test_find_block_finds_v2_blocks(self):
        for b in self.chapter()["blocks"] + self.projects["beta"]["streams"][0]["blocks"]:
            self.assertEqual(find_block(self.weeks, b["id"]), b)
        self.assertIsNone(find_block(self.weeks, f"{WEEK}:alpha:{C3}:heading:0"))

    def test_package_paths_cannot_escape_the_week_folder(self):
        data = json.loads((self.weeks / WEEK / "outcomes.json").read_text(encoding="utf-8"))
        (self.weeks / "secret.png").write_bytes(b"x")
        ev = data["projects"]["C--Claude-alpha"]["evidence"][0]
        ev["package"] = {"href": "../secret.png", "preview": "C:/Windows/win.ini", "files": ["/etc/passwd", "pages/../../secret.png"]}
        (self.weeks / WEEK / "outcomes.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        blocks = next(s for s in build_library(self.weeks)[0]["projects"][0]["streams"] if s["chapter"] == C1)["blocks"]
        self.assertFalse([b for b in blocks if b.get("eid") == "E-aPAGE1"])

    def test_v1_and_v2_weeks_side_by_side(self):
        from tests.test_library import OUTCOMES
        w = self.weeks / "2026-W42"
        w.mkdir()
        (w / "outcomes.json").write_text(json.dumps(OUTCOMES, ensure_ascii=False), encoding="utf-8")
        lib = {x["week"]: x for x in build_library(self.weeks)}
        self.assertEqual(lib["2026-W42"]["schema"], 1)
        self.assertEqual(lib["2026-W42"]["projects"][0]["streams"][0]["id"], "2026-W42:alpha:0")
        self.assertEqual(lib[WEEK]["schema"], 2)


if __name__ == "__main__":
    unittest.main()
