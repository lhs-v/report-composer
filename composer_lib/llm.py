"""Language-model providers for the composer: one vocabulary table and a small adapter per command-line tool.

Every provider is a CLI the user already has and is signed in to; the composer holds no keys. A prompt goes in on
stdin, text comes out, and a failure is an `LlmError` with a message the UI can show. `FallbackProvider` tries a
second provider once when the first fails; `FakeProvider` is for tests."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

from .polish import resolve_command

# Model names follow the vocabulary table; a name outside it can still be typed in the settings (a warning only).
PROVIDERS: dict[str, dict] = {
    "claude": {"label": "Claude CLI", "command": "claude", "models": ["sonnet", "opus", "haiku"], "default": "sonnet"},
    "gemini": {"label": "Gemini CLI", "command": "gemini", "models": ["gemini-3.8-flash", "gemini-3.8-pro"], "default": "gemini-3.8-flash"},
    "codex": {"label": "Codex CLI", "command": "codex", "models": ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.5"], "default": "gpt-6-astra"},
}
DEFAULT_SYSTEM = ("너는 한 주의 업무 보고를 다른 팀 사람과 관리자가 읽을 글로 다듬는 편집자다. "
                  "묻는 형식 그대로만 답하고, 입력에 없는 사실·숫자를 만들지 않는다.")
GEMINI_P_FLAG = "Follow the instructions given on stdin."
TIMEOUT = 240


class LlmError(Exception):
    pass


@dataclass
class ProviderSpec:
    provider: str
    command: str = ""
    model: str = ""

    def resolved_command(self) -> str:
        return self.command or PROVIDERS.get(self.provider, {}).get("command", "")

    def resolved_model(self) -> str:
        return self.model or PROVIDERS.get(self.provider, {}).get("default", "")


def default_runner(cmd: list[str], text: str, timeout: int, cwd=None, env=None) -> tuple[int, str, str]:
    p = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       cwd=str(cwd) if cwd else None, env=env, shell=cmd[0].lower().endswith((".cmd", ".bat")))
    return p.returncode, p.stdout, p.stderr


class CliProvider:
    def __init__(self, spec: ProviderSpec, runner=None, timeout: int = TIMEOUT, cwd=None):
        if spec.provider not in PROVIDERS:
            raise LlmError(f"알 수 없는 공급자입니다: {spec.provider!r}")
        self.spec = spec
        self._injected = runner is not None
        self.runner = runner or default_runner
        self.timeout = timeout
        self.cwd = cwd
        self.label = PROVIDERS[spec.provider]["label"]

    def _exe(self) -> list[str]:
        command = self.spec.resolved_command()
        try:
            return resolve_command(command)
        except FileNotFoundError:
            if self._injected:                       # a test runner stands in for the program; nothing to look up
                return [command]
            raise LlmError(f"'{command}' 명령을 찾지 못했습니다. {self.label}가 설치되어 있는지 확인하고, "
                           f"설정에서 명령의 전체 경로를 적어 주세요.") from None

    def available(self) -> bool:
        try:
            resolve_command(self.spec.resolved_command())
            return True
        except FileNotFoundError:
            return False

    def argv(self, system: str | None = None) -> list[str]:
        exe, model = self._exe(), self.spec.resolved_model()
        if self.spec.provider == "claude":
            return [*exe, "-p", "--output-format", "json", "--tools", "", "--permission-mode", "dontAsk", "--model", model,
                    "--strict-mcp-config", "--disable-slash-commands", "--no-chrome", "--no-session-persistence",
                    "--system-prompt", system or DEFAULT_SYSTEM, "--exclude-dynamic-system-prompt-sections"]
        if self.spec.provider == "gemini":
            return [*exe, "-m", model, "-p", GEMINI_P_FLAG]
        return [*exe, "exec", "--model", model, "--skip-git-repo-check", "-"]       # codex

    def _env(self) -> dict:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        if self.spec.provider == "claude":
            for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
                env.pop(k, None)
        elif self.spec.provider == "gemini":
            # since Gemini CLI 0.39 a headless run in a folder nobody trusted exits with 55
            env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
        return env

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        cmd = self.argv(system)
        stdin = prompt
        if self.spec.provider == "gemini":
            stdin = f"{system}\n\n{prompt}" if system else prompt
        elif self.spec.provider == "codex" and system:
            stdin = f"{system}\n\n{prompt}"
        try:
            code, out, err = self.runner(cmd, stdin, self.timeout, cwd=self.cwd, env=self._env())
        except subprocess.TimeoutExpired:
            raise LlmError(f"{self.label}가 {self.timeout}초 안에 답하지 않았습니다") from None
        except OSError as e:
            raise LlmError(f"{self.label}를 실행하지 못했습니다: {e}") from e
        out, err = out or "", err or ""
        if self.spec.provider == "gemini" and code == 55:
            raise LlmError("Gemini CLI가 이 폴더를 신뢰할 수 없다고 멈췄습니다(종료 코드 55). 컴포저 작업 폴더"
                           f"({self.cwd or os.getcwd()})에서 `gemini`를 한 번 띄워 '이 폴더를 신뢰'를 고르세요.")
        if code != 0 and not out.strip():
            raise LlmError(f"{self.label} 오류 (종료 코드 {code}): {err.strip()[-300:]}")
        return self._answer(out, err)

    def _answer(self, out: str, err: str) -> str:
        if self.spec.provider == "claude":
            try:
                payload = json.loads(out)
            except json.JSONDecodeError:
                raise LlmError(f"{self.label}가 JSON이 아닌 답을 주었습니다: {out[:200]}") from None
            result = payload.get("result") or ""
            if payload.get("subtype") != "success" or payload.get("is_error") or result.startswith("Failed to authenticate"):
                raise LlmError(f"{self.label} 호출 실패: {result[:200] or payload.get('subtype')}")
            text = result
        elif self.spec.provider == "codex":
            paras = [p.strip() for p in re.split(r"\n\s*\n", out) if p.strip()]
            text = paras[-1] if paras else ""
        else:
            text = out.strip()
        if not text.strip():
            raise LlmError(f"{self.label}의 답이 비어 있습니다. 모델 이름이 맞는지, 로그인이 되어 있는지 확인해 주세요."
                           + (f" ({err.strip()[-300:]})" if err.strip() else ""))
        return text.strip()


class FallbackProvider:
    """Ask `primary`; when it raises `LlmError`, ask `fallback` once. `last` says who answered."""

    def __init__(self, primary, fallback=None):
        self.primary, self.fallback = primary, fallback
        self.last = ""

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        try:
            answer = self.primary.complete(prompt, system=system)
            self.last = "primary"
            return answer
        except LlmError as first:
            if self.fallback is None:
                raise
            try:
                answer = self.fallback.complete(prompt, system=system)
            except LlmError as second:
                raise LlmError(f"{first} / 폴백도 실패했습니다: {second}") from second
            self.last = "fallback"
            return answer


@dataclass
class FakeProvider:
    responses: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append(prompt)
        if not self.responses:
            raise LlmError("FakeProvider에 남은 응답이 없습니다")
        return self.responses.pop(0)
