"""Polish a rough draft with the Gemini CLI (stdlib only; the CLI itself is whatever `gemini` is on the PATH).

The draft's text blocks go out as markdown; pictures, files and column layouts stay home and travel only as
`[[B:n]]` placeholders the model must keep in place. The answer comes back as markdown and becomes a *new* draft
beside the rough one, so nothing the user assembled is overwritten. No file content and no local paths leave."""
from __future__ import annotations

import copy
import os
import re
import secrets
import shlex
import shutil
import subprocess

TEXT_TYPES = ("heading", "paragraph", "bullets", "table", "callout", "divider")
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_INSTRUCTIONS = ("이 글은 한 주 동안의 업무를 다른 팀 사람과 관리자도 읽는 주간 보고입니다. 배경을 모르는 사람도 이해할 수 있게, "
                        "짧은 메모를 완전한 문장으로 풀고 흐름이 이어지게 다듬어 주세요. 전문 용어는 처음 나올 때 한 번 쉽게 풀어 쓰고, "
                        "과장하지 말고 담백하게, 전체 길이는 원문의 1.5배를 넘지 않게 해 주세요.")
TIMEOUT = 240


class PolishError(Exception):
    pass


def _ph(n: int) -> str:
    return f"[[B:{n}]]"


def to_markdown(blocks: list[dict]) -> tuple[str, dict[str, dict]]:
    """(markdown with placeholders, {placeholder: original block})."""
    out: list[str] = []
    kept: dict[str, dict] = {}
    for n, b in enumerate(blocks, 1):
        t = b.get("type")
        if t == "heading":
            out.append(("### " if b.get("level") == 3 else "## ") + (b.get("text") or ""))
        elif t == "paragraph":
            out.append(b.get("text") or "")
        elif t == "bullets":
            out.append("\n".join(f"- {it}" for it in (b.get("items") or []) if str(it).strip()))
        elif t == "table":
            rows = [[str(c).replace("|", "／").replace("\n", " ") for c in r] for r in (b.get("rows") or [])]
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append("\n".join(lines))
        elif t == "callout":
            out.append("\n".join("> " + line for line in (b.get("text") or "").split("\n")))
        elif t == "divider":
            out.append("---")
        else:                                              # image, file, columns, anything new: a placeholder
            ph = _ph(n)
            kept[ph] = b
            out.append(ph)
    return "\n\n".join(x for x in out if x is not None), kept


def _new_id() -> str:
    return "b-" + secrets.token_hex(4)


def _fresh(block: dict) -> dict:
    b = copy.deepcopy(block)
    b["id"] = _new_id()
    if b.get("type") == "columns":
        for col in b.get("cols") or []:
            for nb in col:
                if isinstance(nb, dict):
                    nb["id"] = _new_id()
    return b


_PH_RE = re.compile(r"^\s*(\[\[B:\d+\]\])\s*$")
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.S)


def from_markdown(text: str, kept: dict[str, dict]) -> list[dict]:
    """Markdown back into draft blocks; placeholders become the original blocks (with new ids); placeholders the
    model dropped are appended at the end so no picture or file is lost."""
    fences = _FENCE_RE.findall(text)
    if fences:                                             # the answer wrapped in a fence (with or without a preamble)
        text = max(fences, key=len)
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[dict] = []
    used: set[str] = set()
    para: list[str] = []
    items: list[str] = []
    quote: list[str] = []
    rows: list[list[str]] = []

    def flush():
        nonlocal para, items, quote, rows
        if para:
            blocks.append({"id": _new_id(), "type": "paragraph", "text": " ".join(s.strip() for s in para)})
            para = []
        if items:
            blocks.append({"id": _new_id(), "type": "bullets", "items": items})
            items = []
        if quote:
            blocks.append({"id": _new_id(), "type": "callout", "text": "\n".join(quote)})
            quote = []
        if rows:
            blocks.append({"id": _new_id(), "type": "table", "rows": rows, "header": True})
            rows = []
    for raw in lines:
        line = raw.rstrip()
        pm = _PH_RE.match(line)
        if pm:
            flush()
            ph = pm.group(1)
            if ph in kept and ph not in used:
                blocks.append(_fresh(kept[ph]))
                used.add(ph)
            continue
        if not line.strip():
            flush()
            continue
        hm = re.match(r"^(#{1,6})\s+(.*)$", line)
        if hm:
            flush()
            blocks.append({"id": _new_id(), "type": "heading", "level": 3 if len(hm.group(1)) >= 3 else 2, "text": hm.group(2).strip()})
            continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            flush()
            blocks.append({"id": _new_id(), "type": "divider"})
            continue
        bm = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", line)
        if bm:
            if para or quote or rows:
                flush()
            items.append(bm.group(1).strip())
            continue
        if line.lstrip().startswith("|"):
            if para or items or quote:
                flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue                                   # the header separator
            rows.append(cells)
            continue
        if line.lstrip().startswith(">"):
            if para or items or rows:
                flush()
            quote.append(line.lstrip()[1:].strip())
            continue
        if items or quote or rows:
            flush()
        para.append(line)
    flush()
    for ph, b in kept.items():                             # anything the model left out comes back at the end
        if ph not in used:
            blocks.append(_fresh(b))
    return blocks


STYLES = {
    "polite": "정중한 보고체(~했습니다/~입니다). 문장은 완전한 문장으로 쓴다.",
    "brief": "개조식(명사형 종결: ~함/~완료/~예정). 한 줄에 한 사실, 조사와 군더더기를 줄인다. 제목·목록 위주로 짧게.",
    "plain": "담백한 평서체(~했다/~이다).",
}
DEFAULT_STYLE = "polite"


def build_prompt(instructions: str, style: str = DEFAULT_STYLE) -> str:
    return (
        "너는 주간 업무 보고서를 다듬는 편집자다. 표준 입력으로 받은 마크다운 초안을 아래 규칙대로 다시 써서 **마크다운만** 출력하라. "
        "설명이나 서문, 코드 펜스는 붙이지 않는다.\n\n"
        "규칙:\n"
        "1. 사실·숫자·고유명사·파일 이름은 바꾸거나 더하지 않는다. 초안에 없는 내용을 지어내지 않는다.\n"
        "2. `[[B:n]]` 꼴의 자리표시자 줄은 그림·파일·표 배치다. 글자 하나 바꾸지 말고 **같은 순서로, 각각 한 줄에 그대로** 남겨라. 빼거나 합치지 않는다.\n"
        "3. 제목은 `##`/`###`, 목록은 `- `, 표는 마크다운 표, 강조 상자는 `> ` 인용으로 쓴다. 다른 서식은 쓰지 않는다.\n"
        "4. 한국어로 쓴다. 영어 고유명사·코드 식별자는 원문 그대로 둔다.\n"
        f"5. 문체: {STYLES.get(style, STYLES[DEFAULT_STYLE])} 느낌표·이모지 없음.\n\n"
        f"다듬는 방향: {instructions.strip() or DEFAULT_INSTRUCTIONS}\n"
    )


STDIN_HEAD = "=== 지시 (아래 규칙대로 그 다음의 초안을 다시 쓴다) ===\n\n"
STDIN_DRAFT = "\n\n=== 초안 (여기부터 다듬을 마크다운) ===\n\n"
# The -p text stays ASCII and one line: on Windows the npm `gemini.cmd` shim passes arguments through cmd.exe,
# which mangles quotes, percent signs and newlines. The real instructions and the draft travel on stdin.
P_FLAG = "Rewrite the draft given on stdin by following the Korean instructions at its top. Output markdown only, nothing else."


def resolve_command(command: str) -> list[str]:
    """The executable to run. A command line with spaces is split; a bare name is looked up on PATH the way
    Windows does (so npm's `gemini.cmd` is found without PowerShell); a `.ps1` alone is of no use here."""
    if " " in command.strip():
        return [part.strip('"') for part in shlex.split(command, posix=False)]
    found = shutil.which(command)
    if found and found.lower().endswith(".ps1"):
        cmd = found[:-4] + ".cmd"
        found = cmd if os.path.isfile(cmd) else None
    if not found and os.name == "nt":                     # npm's usual place, even when PATH lacks it in this session
        guess = os.path.join(os.environ.get("APPDATA", ""), "npm", command + ".cmd")
        found = guess if os.path.isfile(guess) else None
    if not found:
        raise FileNotFoundError(command)
    return [found]


def default_runner(cmd: list[str], text: str, timeout: int, cwd=None) -> tuple[int, str, str]:
    # GEMINI_CLI_TRUST_WORKSPACE: since Gemini CLI 0.39 a headless run in a folder nobody trusted exits with 55
    # ("not running in a trusted directory"); the composer's own workspace folder is the one it runs in.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "GEMINI_CLI_TRUST_WORKSPACE": "true"}
    p = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
                       cwd=str(cwd) if cwd else None)
    return p.returncode, p.stdout, p.stderr


def polish_draft(drafts, draft_id: str, model: str, instructions: str, command: str = "gemini", runner=None, timeout: int = TIMEOUT,
                 cwd=None, style: str = DEFAULT_STYLE) -> dict:
    """Run the CLI on the draft's text (in `cwd`, the composer's workspace) and save the answer as a new draft
    `<title> · 다듬음`. Raises PolishError with a message the UI can show."""
    if runner is None:
        import functools
        runner = functools.partial(default_runner, cwd=cwd)
    src = drafts.get(draft_id)
    if src is None:
        raise PolishError("초안을 찾지 못했습니다")
    md, kept = to_markdown(src.get("blocks") or [])
    if not any(b.get("type") in TEXT_TYPES and b.get("type") != "divider" for b in src.get("blocks") or []):
        raise PolishError("다듬을 글이 없습니다: 문단이나 제목을 먼저 몇 줄 넣어 주세요")
    try:
        exe = resolve_command(command)
    except FileNotFoundError:
        raise PolishError(f"'{command}' 명령을 찾지 못했습니다. Gemini CLI가 설치되어 있으면 composer.config.json의 gemini.command에 "
                          f"전체 경로를 적어 주세요 (보통 %APPDATA%\\npm\\gemini.cmd). 설치: npm i -g @google/gemini-cli, 로그인: gemini.")
    cmd = [*exe, "-m", model or DEFAULT_MODEL, "-p", P_FLAG]
    stdin = STDIN_HEAD + build_prompt(instructions, style) + STDIN_DRAFT + md
    try:
        code, out, err = runner(cmd, stdin, timeout)
    except FileNotFoundError:
        raise PolishError(f"'{exe[0]}' 을(를) 실행하지 못했습니다. Gemini CLI가 설치되어 있는지 확인해 주세요.")
    except subprocess.TimeoutExpired:
        raise PolishError(f"{timeout}초 안에 답이 오지 않았습니다. 초안을 나누거나 다시 시도해 주세요.")
    if code != 0:
        tail = (err or out or "").strip()[-600:]
        hint = ("\n폴더 신뢰 문제입니다: 컴포저는 GEMINI_CLI_TRUST_WORKSPACE=true로 실행하지만 CLI가 이를 무시하면, cmd에서 "
                f"컴포저 작업 폴더({cwd or os.getcwd()})로 이동해 `gemini`를 한 번 띄우고 '이 폴더를 신뢰'를 고르세요." if "trusted directory" in tail else "")
        raise PolishError(f"Gemini CLI 오류 (종료 코드 {code}): {tail}{hint}")
    if not (out or "").strip():
        raise PolishError("Gemini의 답이 비어 있습니다. 모델 이름이 맞는지, 로그인이 되어 있는지 확인해 주세요." + (f" ({err.strip()[-300:]})" if err and err.strip() else ""))
    out = "\n".join(line for line in out.split("\n") if not line.strip().startswith("=== "))   # our own section markers, echoed
    blocks = from_markdown(out, kept)
    if not blocks:
        raise PolishError("답을 초안으로 바꾸지 못했습니다: " + out.strip()[:300])
    new = drafts.create(f"{src.get('title', '')} · 다듬음")
    new["blocks"] = blocks
    new["polished_from"] = draft_id
    new["polish"] = {"model": model or DEFAULT_MODEL, "instructions": instructions, "style": style, "at": new["created"]}
    return drafts.save(new)
