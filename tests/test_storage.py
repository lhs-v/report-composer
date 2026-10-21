import unittest

from composer_lib.storage import attachment_name, inline_md, render, validate

BLOCKS = [
    {"id": "1", "type": "heading", "level": 2, "text": "두 필터 비교"},
    {"id": "2", "type": "paragraph", "text": "a < b **굵게** _기울임_ `code` [링크](https://wiki/x)"},
    {"id": "3", "type": "bullets", "items": ["첫째", "둘째 & 셋째"]},
    {"id": "4", "type": "image", "src": "2026-W42/pages/alpha-01/preview.png", "caption": "캡처 1"},
    {"id": "5", "type": "file", "src": "2026-W42/pages/alpha-01/media/v.mp4", "caption": "비교 영상"},
    {"id": "6", "type": "divider"},
    {"id": "7", "type": "callout", "text": "지금 어디까지: 비교 완료"},
]


class StorageTests(unittest.TestCase):
    def test_inline_markdown_escapes_then_formats(self):
        self.assertEqual(inline_md("a < b **c**"), "a &lt; b <strong>c</strong>")
        self.assertEqual(inline_md("_i_ `x<y` [t](https://u?a=1&b=2)"),
                         '<em>i</em> <code>x&lt;y</code> <a href="https://u?a=1&amp;b=2">t</a>')

    def test_attachment_names_are_flat_and_unique_per_path(self):
        a = attachment_name("2026-W42/pages/alpha-01/preview.png")
        b = attachment_name("2026-W42/pages/alpha-02/preview.png")
        self.assertEqual(a, "2026-W42_pages_alpha-01_preview.png")
        self.assertNotEqual(a, b)

    def test_render_produces_expected_storage_markup(self):
        x = render(BLOCKS)
        self.assertIn("<h2>두 필터 비교</h2>", x)
        self.assertIn('<p>a &lt; b <strong>굵게</strong> <em>기울임</em> <code>code</code> <a href="https://wiki/x">링크</a></p>', x)
        self.assertIn("<ul><li>첫째</li><li>둘째 &amp; 셋째</li></ul>", x)
        self.assertIn('<ac:image ac:width="800"><ri:attachment ri:filename="2026-W42_pages_alpha-01_preview.png"/></ac:image>', x)
        self.assertIn("<p><em>캡처 1</em></p>", x)
        self.assertIn('<ac:link><ri:attachment ri:filename="2026-W42_pages_alpha-01_media_v.mp4"/><ac:plain-text-link-body><![CDATA[비교 영상]]></ac:plain-text-link-body></ac:link>', x)
        self.assertIn("<hr/>", x)
        self.assertIn('<ac:structured-macro ac:name="info"><ac:rich-text-body><p>지금 어디까지: 비교 완료</p></ac:rich-text-body></ac:structured-macro>', x)

    def test_rendered_markup_is_well_formed(self):
        self.assertIsNone(validate(render(BLOCKS)))
        self.assertIsNotNone(validate("<p>broken"))


if __name__ == "__main__":
    unittest.main()
