import json
import unittest

from composer_lib.llm import PROVIDERS, CliProvider, FakeProvider, FallbackProvider, LlmError, ProviderSpec


def runner_ok(answer):
    calls = []
    def run(cmd, text, timeout, cwd=None, env=None):
        calls.append({"cmd": cmd, "text": text, "env": env})
        return 0, answer, ""
    run.calls = calls
    return run


class VocabTests(unittest.TestCase):
    def test_every_provider_has_a_command_models_and_a_default_in_its_models(self):
        for name, p in PROVIDERS.items():
            self.assertTrue(p["command"], name)
            self.assertIn(p["default"], p["models"], name)

    def test_spec_fills_command_and_model_from_the_table(self):
        s = ProviderSpec("gemini")
        self.assertEqual((s.resolved_command(), s.resolved_model()), ("gemini", "gemini-3.8-flash"))
        self.assertEqual(ProviderSpec("claude", model="opus").resolved_model(), "opus")


class ArgvTests(unittest.TestCase):
    def test_claude_argv_disables_tools_and_mcp_and_reads_the_prompt_from_stdin(self):
        run = runner_ok(json.dumps({"subtype": "success", "result": "답", "is_error": False}))
        p = CliProvider(ProviderSpec("claude", command="claude.exe", model="sonnet"), runner=run)
        self.assertEqual(p.complete("질문", system="S"), "답")
        cmd, text, env = run.calls[0]["cmd"], run.calls[0]["text"], run.calls[0]["env"]
        for flag in ("-p", "--tools", "--strict-mcp-config", "--no-session-persistence", "--system-prompt"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(text, "질문")
        self.assertNotIn("CLAUDECODE", env)

    def test_claude_error_payload_is_an_llm_error(self):
        run = runner_ok(json.dumps({"subtype": "error", "result": "Failed to authenticate", "is_error": True}))
        with self.assertRaises(LlmError):
            CliProvider(ProviderSpec("claude", command="claude.exe"), runner=run).complete("x")

    def test_gemini_argv_sends_system_and_prompt_on_stdin_and_trusts_the_workspace(self):
        run = runner_ok("답")
        p = CliProvider(ProviderSpec("gemini", command="gemini.cmd"), runner=run, cwd="C:/ws")
        self.assertEqual(p.complete("질문", system="S"), "답")
        c = run.calls[0]
        self.assertEqual(c["cmd"][1:3], ["-m", "gemini-3.8-flash"])
        self.assertIn("S", c["text"]); self.assertIn("질문", c["text"])
        self.assertEqual(c["env"].get("GEMINI_CLI_TRUST_WORKSPACE"), "true")

    def test_gemini_exit_55_explains_folder_trust(self):
        def run(cmd, text, timeout, cwd=None, env=None):
            return 55, "", "not running in a trusted directory"
        with self.assertRaises(LlmError) as cm:
            CliProvider(ProviderSpec("gemini", command="gemini.cmd"), runner=run).complete("x")
        self.assertIn("신뢰", str(cm.exception))

    def test_codex_argv_uses_exec_and_keeps_the_whole_stdout_without_ansi_codes(self):
        run = runner_ok("\x1b[1m첫 문단\x1b[0m\n\n둘째 문단\n\x1b[0m")
        p = CliProvider(ProviderSpec("codex", command="codex.cmd"), runner=run)
        self.assertEqual(p.complete("질문"), "첫 문단\n\n둘째 문단")
        self.assertEqual(run.calls[0]["cmd"][1], "exec")

    def test_claude_json_that_is_not_an_object_is_an_llm_error(self):
        with self.assertRaises(LlmError) as cm:
            CliProvider(ProviderSpec("claude", command="claude.exe"), runner=runner_ok("null")).complete("x")
        self.assertIn("알 수 없는 답", str(cm.exception))

    def test_a_missing_command_is_not_available_and_raises_a_korean_error(self):
        p = CliProvider(ProviderSpec("gemini", command="no-such-cli-xyz"))
        self.assertFalse(p.available())
        with self.assertRaises(LlmError) as cm:
            p.complete("x")
        self.assertIn("명령을 찾지 못했습니다", str(cm.exception))


class FallbackTests(unittest.TestCase):
    def test_fallback_answers_once_when_the_primary_fails(self):
        f = FallbackProvider(FakeProvider([]), FakeProvider(["폴백 답"]))
        self.assertEqual(f.complete("q"), "폴백 답")
        self.assertEqual(f.last, "fallback")

    def test_without_fallback_the_error_propagates(self):
        with self.assertRaises(LlmError):
            FallbackProvider(FakeProvider([]), None).complete("q")

    def test_last_is_cleared_when_a_later_call_fails_on_both_sides(self):
        f = FallbackProvider(FakeProvider(["ok"]), FakeProvider([]))
        self.assertEqual(f.complete("q"), "ok")
        self.assertEqual(f.last, "primary")
        with self.assertRaises(LlmError):
            f.complete("q")
        self.assertEqual(f.last, "")
