import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.config import LlmConfig, load_config, save_llm


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
            self.assertEqual(cfg.confluence.email, "")
            self.assertNotIn("secret", json.dumps(cfg.public()))

    def test_missing_file_gives_defaults_without_confluence(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "does-not-exist-composer.json")
        self.assertEqual(cfg.confluence.base_url, "")
        self.assertFalse(cfg.confluence.configured)

    def test_llm_key_is_read_and_an_old_gemini_key_migrates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "composer.config.json"
            p.write_text(json.dumps({"gemini": {"command": "C:/g/gemini.cmd", "model": "gemini-3.8-pro"}}), encoding="utf-8")
            cfg = load_config(p)
            self.assertEqual((cfg.llm.provider, cfg.llm.command, cfg.llm.model), ("gemini", "C:/g/gemini.cmd", "gemini-3.8-pro"))
            self.assertIsNone(cfg.llm.fallback)
            p.write_text(json.dumps({"llm": {"provider": "claude", "model": "sonnet", "fallback": {"provider": "gemini"}}, "confluence": {"pat": "keep-me"}}), encoding="utf-8")
            cfg = load_config(p)
            self.assertEqual((cfg.llm.provider, cfg.llm.fallback.provider), ("claude", "gemini"))
            save_llm(p, LlmConfig(provider="gemini", command="", model="gemini-3.8-flash", fallback=None))
            raw = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(raw["llm"]["provider"], "gemini")
            self.assertEqual(raw["confluence"]["pat"], "keep-me")          # untouched
            self.assertEqual(load_config(Path(tmp) / "none.json").llm.provider, "")
            pub = load_config(p).public()
            self.assertIn("providers", pub); self.assertEqual(pub["llm"]["provider"], "gemini")

    def test_save_llm_creates_a_missing_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sub" / "composer.config.json"
            save_llm(p, LlmConfig(provider="claude"))
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["llm"]["provider"], "claude")
            self.assertEqual(load_config(p).llm.provider, "claude")


if __name__ == "__main__":
    unittest.main()
