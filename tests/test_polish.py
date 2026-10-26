"""Polishing a rough draft with the Gemini CLI: the text goes out as markdown with placeholders for pictures and
files, comes back rewritten, and lands in a new draft beside the rough one; nothing non-text is lost."""
import json
import tempfile
import unittest
from pathlib import Path

from composer_lib import polish
from composer_lib.drafts import Drafts

ROUGH = [
    {"id": "b1", "type": "heading", "level": 2, "text": "골격"},
    {"id": "b2", "type": "paragraph", "text": "맵 만듬. 갤러리 비교. 결과 괜찮"},
    {"id": "b3", "type": "image", "src": "2026-W43/records/watch-pose/R-1/skeleton-map.png", "caption": "골격 지도", "source_ref": "x:1"},
    {"id": "b4", "type": "bullets", "items": ["정확도 92", "속도 ok"]},
    {"id": "b5", "type": "file", "src": "2026-W43/records/a/R-2/v.720p.mp4", "caption": "시연 영상"},
    {"id": "b6", "type": "table", "rows": [["항목", "값"], ["FPS", "30"]], "header": True},
    {"id": "b7", "type": "callout", "text": "**주의**\n실험 데이터만"},
    {"id": "b8", "type": "columns", "cols": [[{"id": "c1", "type": "paragraph", "text": "왼쪽"}], [{"id": "c2", "type": "paragraph", "text": "오른쪽"}]]},
]


class MarkdownRoundTrip(unittest.TestCase):
    def test_text_goes_out_as_markdown_and_everything_else_as_a_placeholder(self):
        md, kept = polish.to_markdown(ROUGH)
        self.assertIn("## 골격", md)
        self.assertIn("맵 만듬. 갤러리 비교. 결과 괜찮", md)
        self.assertIn("[[B:3]]", md)                                            # the picture
        self.assertIn("[[B:5]]", md)                                            # the file
        self.assertIn("[[B:8]]", md)                                            # columns travel whole
        self.assertIn("- 정확도 92", md)
        self.assertIn("| 항목 | 값 |", md)
        self.assertIn("> **주의**", md)
        self.assertNotIn("skeleton-map.png", md)                               # no paths leave
        self.assertEqual(sorted(kept), ["[[B:3]]", "[[B:5]]", "[[B:8]]"])

    def test_the_answer_becomes_blocks_with_the_placeholders_put_back_in_order(self):
        _, kept = polish.to_markdown(ROUGH)
        answer = """## 골격 추정 결과

골격 지도를 만들고 갤러리와 비교했더니 결과가 좋았습니다.

[[B:3]]

- 정확도 92%로 목표를 넘었습니다.
- 속도도 충분합니다.

[[B:5]]

| 항목 | 값 |
|---|---|
| FPS | 30 |

> **주의**
> 실험 데이터로만 확인한 결과입니다.

[[B:8]]
"""
        blocks = polish.from_markdown(answer, kept)
        self.assertEqual([b["type"] for b in blocks], ["heading", "paragraph", "image", "bullets", "file", "table", "callout", "columns"])
        self.assertEqual(blocks[0]["text"], "골격 추정 결과")
        self.assertEqual(blocks[2]["src"], ROUGH[2]["src"])                     # the picture is the original block
        self.assertEqual(blocks[2]["caption"], "골격 지도")
        self.assertEqual(blocks[3]["items"], ["정확도 92%로 목표를 넘었습니다.", "속도도 충분합니다."])
        self.assertEqual(blocks[5]["rows"], [["항목", "값"], ["FPS", "30"]])
        self.assertTrue(blocks[5]["header"])
        self.assertEqual(blocks[6]["text"], "**주의**\n실험 데이터로만 확인한 결과입니다.")
        self.assertEqual(blocks[7]["type"], "columns")
        self.assertTrue(all(b.get("id") for b in blocks))
        self.assertNotEqual(blocks[0]["id"], "b1")                              # new ids: it is a new draft

    def test_a_placeholder_the_model_dropped_is_appended_so_nothing_is_lost(self):
        _, kept = polish.to_markdown(ROUGH)
        blocks = polish.from_markdown("## 골격\n\n좋았습니다.\n\n[[B:5]]\n", kept)
        self.assertEqual([b["type"] for b in blocks], ["heading", "paragraph", "file", "image", "columns"])

    def test_code_fences_and_a_stray_preamble_are_tolerated(self):
        _, kept = polish.to_markdown(ROUGH[:2])
        blocks = polish.from_markdown("다듬은 결과입니다:\n```markdown\n## 골격\n\n문장.\n```\n", kept)
        self.assertEqual([(b["type"], b["text"]) for b in blocks], [("heading", "골격"), ("paragraph", "문장.")])


class RunTests(unittest.TestCase):
    def test_polish_calls_the_cli_with_the_model_and_the_prompt_and_makes_a_new_draft(self):
        calls = []

        def runner(cmd, text, timeout):
            calls.append((cmd, text, timeout))
            return 0, "## 골격 추정 결과\n\n다듬은 문장.\n\n[[B:3]]\n", ""
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Drafts(Path(tmp))
            rough = drafts.create("주간 성과 2026-W43")
            rough["blocks"] = ROUGH[:3]
            drafts.save(rough)
            import sys
            new = polish.polish_draft(drafts, rough["id"], model="gemini-3.8-flash", instructions="모든 사람이 이해하게",
                                      command=f'"{sys.executable}" gemini', runner=runner)
            self.assertEqual(calls[0][0][1:4], ["gemini", "-m", "gemini-3.8-flash"])
            self.assertIn("-p", calls[0][0])
            flag = calls[0][0][calls[0][0].index("-p") + 1]
            self.assertTrue(flag.isascii() and "\n" not in flag)                 # cmd.exe-safe: the real prompt rides on stdin
            stdin = calls[0][1]
            self.assertIn("모든 사람이 이해하게", stdin)
            self.assertIn("[[B:n]]", stdin)                                      # the rule about placeholders
            self.assertIn("맵 만듬", stdin)                                      # then the draft
            self.assertLess(stdin.index("[[B:n]]"), stdin.index("맵 만듬"))
            self.assertEqual(new["title"], "주간 성과 2026-W43 · 다듬음")
            echoed = polish.polish_draft(drafts, rough["id"], model="m", instructions="", command=f'"{sys.executable}" gemini',
                                         runner=lambda c, t, to: (0, "=== 초안 (여기부터 다듬을 마크다운) ===

## 제목

문장.

[[B:3]]
", ""))
            self.assertEqual([b["type"] for b in echoed["blocks"]], ["heading", "paragraph", "image"])   # a marker the model echoed is dropped
            self.assertEqual([b["type"] for b in new["blocks"]], ["heading", "paragraph", "image"])
            self.assertEqual(new["blocks"][2]["src"], ROUGH[2]["src"])
            self.assertEqual(new["polished_from"], rough["id"])
            self.assertEqual(drafts.get(rough["id"])["blocks"], ROUGH[:3])        # the rough draft is untouched
            self.assertIn(new["id"], [d["id"] for d in drafts.list()])

    def test_cli_failures_are_reported_as_errors_the_ui_can_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Drafts(Path(tmp))
            rough = drafts.create("t")
            rough["blocks"] = ROUGH[:2]
            drafts.save(rough)
            import sys
            here = f'"{sys.executable}" gemini'
            with self.assertRaises(polish.PolishError) as cm:
                polish.polish_draft(drafts, rough["id"], model="m", instructions="", command=here, runner=lambda c, t, to: (1, "", "model not found: m"))
            self.assertIn("model not found", str(cm.exception))
            with self.assertRaises(polish.PolishError) as cm:
                polish.polish_draft(drafts, rough["id"], model="m", instructions="", command=here, runner=lambda c, t, to: (0, "   ", ""))
            self.assertIn("비어", str(cm.exception))
            with self.assertRaises(polish.PolishError) as cm:                    # a bare name that is not on PATH
                polish.polish_draft(drafts, rough["id"], model="m", instructions="", command="no-such-gemini-xyz", runner=lambda c, t, to: (0, "x", ""))
            self.assertIn("no-such-gemini-xyz", str(cm.exception))
            self.assertIn("gemini.command", str(cm.exception))
            with self.assertRaises(polish.PolishError):
                polish.polish_draft(drafts, rough["id"], model="m", instructions="", command=here, runner=lambda c, t, to: (0, "", ""))
            empty = drafts.create("빈 초안")
            with self.assertRaises(polish.PolishError) as cm:
                polish.polish_draft(drafts, empty["id"], model="m", instructions="", command=here, runner=lambda c, t, to: (0, "x", ""))
            self.assertIn("글", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
