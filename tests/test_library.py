import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.library import build_library, find_block

OUTCOMES = {
    "week": "2026-W42", "since": "2026-10-12", "until": "2026-10-18",
    "projects": {"C--Claude-alpha": {
        "project": "C--Claude-alpha", "error": None,
        "streams": [{"title": "두 필터 비교", "problem": "어느 필터가 나은지 몰랐다.", "approach": "나란히 비교했다.",
                     "results": [{"text": "월드 정합이 더 오래 유지", "evidence": [1]}, {"text": "증거 없는 결과", "evidence": []}],
                     "status": "비교 완료", "next": "실녹음 재확인"}],
        "evidence": [{"n": 1, "kind": "artifact", "url": "https://claude.ai/artifact/ABC", "path": "C:/x/index.html",
                      "title": "비교 영상", "when": "2026-10-13T00:00:00+00:00", "files": [["media/v.mp4", "C:/x/media/v.mp4"]]}],
    }},
}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.weeks = Path(self.tmp.name) / "weeks"
        w = self.weeks / "2026-W42"
        (w / "pages" / "alpha-01" / "media").mkdir(parents=True)
        (w / "assets").mkdir()
        (w / "outcomes.json").write_text(json.dumps(OUTCOMES, ensure_ascii=False), encoding="utf-8")
        (w / "pages" / "alpha-01" / "index.html").write_text("<p>page</p>", encoding="utf-8")
        (w / "pages" / "alpha-01" / "preview.png").write_bytes(b"PNG")
        (w / "pages" / "alpha-01" / "media" / "v.mp4").write_bytes(b"0" * 2048)
        (w / "alpha-01-two-filters.md").write_text("# 두 필터 비교\n본문", encoding="utf-8")
        (w / "README.md").write_text("# 주간 성과 보고", encoding="utf-8")
        (w / "weekly.md").write_text("# 주간 보고 W42", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocks_are_split_with_stable_ids_and_relative_sources(self):
        lib = build_library(self.weeks)
        self.assertEqual([w["week"] for w in lib], ["2026-W42"])
        proj = lib[0]["projects"][0]
        self.assertEqual(proj["short"], "alpha")
        stream = proj["streams"][0]
        types = [b["type"] for b in stream["blocks"]]
        self.assertEqual(types[:3], ["heading", "paragraph", "paragraph"])
        self.assertEqual(types.count("bullet"), 2)
        self.assertIn("image", types)
        self.assertIn("file", types)
        self.assertIn("page", types)
        self.assertIn("markdown", types)
        self.assertEqual(stream["blocks"][0]["id"], "2026-W42:alpha:0:heading:0")
        self.assertEqual(stream["blocks"][0]["text"], "두 필터 비교")
        para = stream["blocks"][1]
        self.assertEqual((para["label"], para["text"]), ("무엇을 풀려고 했나", "어느 필터가 나은지 몰랐다."))
        bullet = next(b for b in stream["blocks"] if b["type"] == "bullet")
        self.assertEqual(bullet["evidence"], [1])
        img = next(b for b in stream["blocks"] if b["type"] == "image")
        self.assertEqual(img["src"], "2026-W42/pages/alpha-01/preview.png")
        self.assertEqual(img["caption"], "비교 영상")
        f = next(b for b in stream["blocks"] if b["type"] == "file")
        self.assertEqual((f["src"], f["size"]), ("2026-W42/pages/alpha-01/media/v.mp4", 2048))
        self.assertEqual(find_block(self.weeks, img["id"])["src"], img["src"])
        self.assertIsNone(find_block(self.weeks, "2026-W42:alpha:9:heading:0"))

    def test_week_level_assets_include_readme_and_weekly_md(self):
        lib = build_library(self.weeks)
        srcs = [a["src"] for a in lib[0]["assets"]]
        self.assertIn("2026-W42/weekly.md", srcs)
        self.assertIn("2026-W42/README.md", srcs)
        wk = next(a for a in lib[0]["assets"] if a["src"].endswith("weekly.md"))
        self.assertEqual(wk["type"], "markdown")
        self.assertTrue(wk["text"].startswith("# 주간 보고"))

    def test_week_without_outcomes_json_falls_back_to_markdown_files(self):
        w = self.weeks / "2026-W41"
        w.mkdir()
        (w / "alpha-01.md").write_text("# 옛 흐름", encoding="utf-8")
        lib = build_library(self.weeks)
        old = next(x for x in lib if x["week"] == "2026-W41")
        self.assertEqual(old["projects"], [])
        self.assertEqual([a["type"] for a in old["assets"]], ["markdown"])


if __name__ == "__main__":
    unittest.main()
