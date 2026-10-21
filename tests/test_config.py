import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.config import load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_and_pat_masking(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            p.write_text(json.dumps({"confluence": {"base_url": "https://wiki.corp/", "pat": "secret", "default_space": "AI"}}), encoding="utf-8")
            cfg = load_config(p)
            self.assertEqual(cfg.port, 8790)
            self.assertTrue(str(cfg.inbox_dir).endswith("report-inbox"))
            self.assertEqual(cfg.confluence.base_url, "https://wiki.corp")     # trailing slash removed
            self.assertEqual(cfg.confluence.pat, "secret")
            self.assertTrue(cfg.confluence.verify_ssl)
            self.assertEqual(cfg.public()["confluence"]["pat"], "***")
            self.assertNotIn("secret", json.dumps(cfg.public()))

    def test_missing_file_gives_defaults_without_confluence(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "does-not-exist-composer.json")
        self.assertEqual(cfg.confluence.base_url, "")
        self.assertFalse(cfg.confluence.configured)


if __name__ == "__main__":
    unittest.main()
