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
        self.assertEqual(blocks[1]["id"], f"{WEEK}:alpha:{C1}:lead:0")
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
        self.assertEqual(sum(1 for b in blocks if b.get("optional") and not b.get("in_page")), 2)
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


class ReviewRegressionTests(unittest.TestCase):
    """The composer v2 review (2026-10-22): hostile ids, re-received weeks, id stability, project-level sentences,
    malformed packages, images among page files, daily_list results, newer schemas."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.weeks = Path(self.tmp.name) / "weeks"
        self.w = write_v2_package(self.weeks)
        self.data = json.loads((self.w / "outcomes.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def rebuild(self):
        (self.w / "outcomes.json").write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        week = build_library(self.weeks)[0]
        return week, {p["short"]: p for p in week["projects"]}

    def test_chapter_ids_that_could_break_out_of_an_attribute_are_replaced_and_duplicates_split(self):
        chs = self.data["projects"]["C--Claude-alpha"]["chapters"]
        chs[0]["id"] = 'C-x" onmouseover="alert(1)'
        chs[1]["id"] = "C-0"
        chs.append(dict(chs[1], title="세 번째"))
        _, projects = self.rebuild()
        ids = [s["chapter"] for s in projects["alpha"]["streams"]]
        self.assertEqual(ids, ["C-0", "C-0-1", "C-0-2"])
        for s in projects["alpha"]["streams"]:
            for b in s["blocks"]:
                self.assertNotIn('"', b["id"])
                self.assertEqual(len(b["id"].split(":")), 5, b["id"])

    def test_the_recorded_md_name_wins_over_an_old_file_with_the_same_number(self):
        (self.w / "alpha-01-old-title.md").write_text("# 예전 제목", encoding="utf-8")
        self.data["projects"]["C--Claude-alpha"]["chapters"][0]["md"] = "alpha-01-f5.md"
        _, projects = self.rebuild()
        mds = [b["caption"] for b in projects["alpha"]["streams"][0]["blocks"] if b["type"] == "markdown" and not b.get("eid")]
        self.assertEqual(mds, ["alpha-01-f5.md"])

    def test_without_a_recorded_name_the_writer_naming_rule_picks_the_file(self):
        (self.w / "alpha-01-old-title.md").write_text("# 예전 제목", encoding="utf-8")
        (self.w / "alpha-01-F5.md").write_text("# F5 실험 결론", encoding="utf-8")   # label "F5" -> slug "F5"
        _, projects = self.rebuild()
        mds = [b["caption"] for b in projects["alpha"]["streams"][0]["blocks"] if b["type"] == "markdown" and not b.get("eid")]
        self.assertEqual(mds, ["alpha-01-F5.md"])

    def test_adding_a_lead_or_losing_a_copy_keeps_the_other_block_ids(self):
        before, _ = self.rebuild()
        ch = self.data["projects"]["C--Claude-alpha"]["chapters"][0]
        ch["lead"] = ""
        (self.w / "texts" / "U-a43e2f42-10131823.md").unlink()        # the text excerpt's copy disappears
        after, _ = self.rebuild()
        ids = lambda wk: {b["id"]: b for p in wk["projects"] for s in p["streams"] for b in s["blocks"]}
        old, new = ids(before), ids(after)
        for role in ("change", "units"):
            key = f"{WEEK}:alpha:{C1}:{role}:0"
            self.assertIn(key, old)
            self.assertEqual(new[key]["text"], old[key]["text"])
        page = f"{WEEK}:alpha:{C1}:page:0"
        self.assertEqual(new[page]["src"], old[page]["src"])

    def test_one_line_and_overview_are_pickable_blocks(self):
        week, projects = self.rebuild()
        one = projects["gamma"]["blocks"][0]
        self.assertEqual((one["id"], one["text"]), (f"{WEEK}:gamma:one_line:paragraph:0", "자잘한 설정만 손봤다."))
        self.assertEqual(find_block(self.weeks, one["id"])["text"], "자잘한 설정만 손봤다.")
        self.assertEqual(find_block(self.weeks, f"{WEEK}:alpha:overview:paragraph:0")["text"], "F5 결론과 받아쓰기 도구 정리")

    def test_a_malformed_project_does_not_take_down_the_library(self):
        self.data["projects"]["C--Claude-alpha"]["chapters"][0]["results"].append({"eid": "x"})
        self.data["projects"]["C--Claude-beta"]["units"] = 5               # not a list
        week, projects = self.rebuild()
        self.assertTrue(projects["alpha"]["streams"])
        self.assertEqual(projects["beta"]["mode"], "error")
        self.assertIn("gamma", projects)

    def test_images_published_with_a_page_are_image_blocks(self):
        page = self.w / "pages" / "zz-unrelated-name"
        (page / "fig.png").write_bytes(b"PNG")
        ev = self.data["projects"]["C--Claude-alpha"]["evidence"][0]
        ev["package"]["files"].append("pages/zz-unrelated-name/fig.png")
        _, projects = self.rebuild()
        fig = next(b for b in projects["alpha"]["streams"][0]["blocks"] if b.get("src", "").endswith("fig.png"))
        self.assertEqual(fig["type"], "image")

    def test_daily_list_projects_show_the_copies_their_package_carries(self):
        (self.w / "assets" / "log.txt").write_text("로그", encoding="utf-8")
        beta = self.data["projects"]["C--Claude-beta"]
        beta["evidence"] = [{"n": 1, "eid": "E-fLOG", "kind": "file", "title": "로그 묶음", "export": "ok", "package": {"href": "assets/log.txt"}}]
        _, projects = self.rebuild()
        blocks = projects["beta"]["streams"][0]["blocks"]
        self.assertTrue(any(b.get("eid") == "E-fLOG" for b in blocks))

    def test_block_ids_are_unique_even_when_a_text_result_sits_beside_the_chapter_md(self):
        ch = self.data["projects"]["C--Claude-alpha"]["chapters"][0]
        ch["results"] = ["E-tU-a43e2f42-10131823"]          # the only result is a reply excerpt (.md)
        week, projects = self.rebuild()
        ids = [b["id"] for p in week["projects"] for s in p["streams"] for b in s["blocks"]] +               [b["id"] for p in week["projects"] for b in p.get("blocks") or []] + [a["id"] for a in week["assets"]]
        self.assertEqual(len(ids), len(set(ids)))
        md = next(b for b in projects["alpha"]["streams"][0]["blocks"] if b["type"] == "markdown" and not b.get("eid"))
        self.assertEqual(md["id"], f"{WEEK}:alpha:{C1}:md:0")
        self.assertEqual(find_block(self.weeks, md["id"])["caption"], "alpha-01-f5.md")

    def test_one_line_projects_offer_the_copies_their_package_carries(self):
        (self.w / "assets" / "small.png").write_bytes(b"PNG")
        gamma = self.data["projects"]["C--Claude-gamma"]
        gamma["evidence"] = [{"n": 1, "eid": "E-fSMALL", "kind": "file", "title": "작은 그림", "export": "ok", "package": {"href": "assets/small.png", "preview": "assets/small.png"}}]
        _, projects = self.rebuild()
        self.assertTrue(any(b.get("eid") == "E-fSMALL" for b in projects["gamma"]["blocks"]))

    def test_pages_of_units_no_chapter_took_are_pickable(self):
        (self.w / "assets" / "loose.csv").write_text("a", encoding="utf-8")
        alpha = self.data["projects"]["C--Claude-alpha"]
        alpha["units"].append({"id": "U-loose-0001", "when": "w", "line": "l", "chapter": None})
        alpha["evidence"].append({"n": 50, "eid": "E-fLOOSE", "kind": "file", "unit": "U-loose-0001", "title": "떠돌이 표", "export": "ok",
                                  "package": {"href": "assets/loose.csv"}})
        _, projects = self.rebuild()
        self.assertTrue(any(b.get("eid") == "E-fLOOSE" for b in projects["alpha"]["blocks"]))

    def test_files_inside_a_page_are_optional_and_marked_as_page_files(self):
        _, projects = self.rebuild()
        audio = next(b for b in projects["alpha"]["streams"][0]["blocks"] if b.get("src", "").endswith("audio/a.mp3"))
        self.assertTrue(audio.get("in_page"))
        self.assertTrue(audio.get("optional"))

    def test_the_first_screen_thumb_is_the_picture_a_chapter_shows(self):
        page = self.w / "pages" / "zz-unrelated-name"
        (page / "preview-top.png").write_bytes(b"PNG-TOP")
        ev = self.data["projects"]["C--Claude-alpha"]["evidence"][0]
        ev["package"]["thumb"] = "pages/zz-unrelated-name/preview-top.png"
        _, projects = self.rebuild()
        img = next(b for b in projects["alpha"]["streams"][0]["blocks"] if b["type"] == "image")
        self.assertTrue(img["src"].endswith("preview-top.png"))

    def test_a_newer_schema_is_read_as_chapters_with_a_warning(self):
        self.data["schema"] = 4                                      # no `records`: read as the chapters it has
        week, projects = self.rebuild()
        self.assertEqual(week["schema"], 2)
        self.assertIn("v4", week["warning"])
        self.assertTrue(projects["alpha"]["streams"])


if __name__ == "__main__":
    unittest.main()
