"""The three writing aids (node body, week summary, record caption): what each sends to the model and how its answer is read.

Inputs are text only: titles, bodies, captions, flow lines and ledger decisions of the nodes that are switched on.
Pictures, file contents, `href`/`files`/`representative` and local paths never enter a prompt. `build()` returns the
prompt together with `source`, the exact input text, and `parse()` refuses an answer whose numbers are not in it."""
from __future__ import annotations

import re

from .outline import LEDGER_LABEL
from .polish import DEFAULT_STYLE, STYLES

KINDS = ("node", "summary", "caption")
NODE_TARGETS = ("claim", "project", "text")
MAX_SUMMARY_LINES = 5
MAX_CAPTION_CHARS = 60
LENGTH_FACTOR = 1.5

SYSTEM = ("너는 주간 업무 보고서를 다듬는 편집자다. 아래 '입력'에 적힌 사실만 쓴다. 입력에 없는 사실·숫자·고유명사를 지어내지 않는다. "
          "설명이나 서문, 코드 펜스 없이 요구한 결과물만 출력한다. 한국어로 쓰고 영어 고유명사·코드 식별자는 원문 그대로 둔다.")

NODE_RULES = ("위 '입력'을 바탕으로 이 항목의 본문을 다시 써라.\n"
              "1. 출력은 본문 한 덩이다. 마크다운 글머리(`- `)는 써도 된다. 제목 줄은 다시 쓰지 않는다.\n"
              "2. 숫자는 입력에 있는 것만 쓴다.\n"
              "3. 길이는 '지금 본문' 글자 수의 {factor}배를 넘지 않는다.\n"
              "4. 문체: {style} 느낌표·이모지 없음.")
SUMMARY_RULES = ("위 '입력'을 바탕으로 이번 주 요약을 써라.\n"
                 "1. 3~5줄. 줄마다 `프로젝트: 문장` 꼴로 쓴다. 프로젝트 이름은 입력에 적힌 그대로 쓴다.\n"
                 "2. 줄 앞에 글머리 기호나 번호를 붙이지 않는다.\n"
                 "3. 숫자는 입력에 있는 것만 쓴다.\n"
                 "4. 문체: {style} 느낌표·이모지 없음.")
CAPTION_RULES = ("위 '입력'의 기록에 붙일 설명을 써라.\n"
                 "1. 정확히 두 줄. 첫 줄은 무엇이 보이는지, 둘째 줄은 왜 중요한지.\n"
                 "2. 줄마다 {chars}자 이내. 글머리 기호나 번호를 붙이지 않는다.\n"
                 "3. 숫자는 입력에 있는 것만 쓴다. 그림이나 파일의 내용은 모르니 짐작하지 않는다.\n"
                 "4. 문체: {style} 느낌표·이모지 없음.")

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_BULLET = re.compile(r"^\s*(?:[-*•·]+|\d+[.)])\s+")


def numbers_in_source(text: str, source: str) -> bool:
    """True when every number of two digits or more (or with a decimal point) in `text` appears in `source`."""
    return not _missing_numbers(text, source)


def _missing_numbers(text: str, source: str) -> list[str]:
    out: list[str] = []
    for num in _NUMBER.findall(text):
        if (len(num) >= 2 or "." in num) and num not in source and num not in out:
            out.append(num)
    return out


def _style(style: str) -> str:
    return STYLES.get(style, STYLES[DEFAULT_STYLE])


def _on_children(draft: dict, node: dict) -> list[dict]:
    nodes = draft.get("nodes") or {}
    return [nodes[c] for c in node.get("children") or [] if c in nodes and nodes[c].get("on")]


def _flow_line(item: dict) -> str:
    when, text = str(item.get("when") or "").strip(), str(item.get("text") or "").strip()
    return f"{when} · {text}" if when and text else text


# A record's title is a bare file name when the home server found nothing better; a file name never goes into a prompt.
_FILE_NAME = re.compile(r"[^\s/\\]+\.([A-Za-z0-9]{1,5})")
_FILE_TOKEN = re.compile(r"(?<!\S)[^\s/\\]+\.(?=[0-9]{0,4}[A-Za-z])[A-Za-z0-9]{1,5}(?=[\s,;:)\]]|$)")


def _safe_title(title) -> str:
    t = str(title or "")
    m = _FILE_NAME.fullmatch(t)
    if m and re.search(r"[A-Za-z]", m.group(1)):
        return "(제목 없음)"
    return _FILE_TOKEN.sub("(파일)", t)


def _child_lines(draft: dict, node: dict, depth: int = 0) -> list[str]:
    """The text of the children that are on, parent first, indented by depth. Off subtrees are skipped whole."""
    pad, out = "  " * depth, []
    for c in _on_children(draft, node):
        kind = c.get("kind")
        if kind == "record":
            cap = " / ".join(x for x in c.get("caption") or [] if str(x).strip())
            label = " · ".join(x for x in (c.get("kind_label"), _safe_title(c.get("title"))) if x)
            out.append(f"{pad}- 기록: {label}" + (f" — {cap}" if cap else ""))
        elif kind == "flow":
            out += [f"{pad}- 흐름: {_flow_line(i)}" for i in c.get("items") or [] if _flow_line(i)]
        elif kind == "ledger":
            out += [f"{pad}- {LEDGER_LABEL.get(i.get('kind'), i.get('kind') or '')}: {i.get('text')}" for i in c.get("items") or [] if i.get("text")]
        else:
            out.append(f"{pad}- {c.get('title') or ''}" + (f": {c['text']}" if str(c.get("text") or "").strip() else ""))
            out += _child_lines(draft, c, depth + 1)
    return out


def _node(draft: dict, node_id: str | None, kinds: tuple[str, ...], what: str) -> dict:
    n = (draft.get("nodes") or {}).get(node_id) if node_id else None
    if not n:
        raise ValueError(f"노드를 찾을 수 없습니다: {node_id}")
    if n.get("kind") not in kinds:
        raise ValueError(f"{what}은(는) {'/'.join(kinds)} 노드에만 쓸 수 있습니다: {n.get('kind')}")
    return n


def _assemble(kind: str, target: dict, rules: str, source: str, before) -> dict:
    prompt = f"{rules}\n\n=== 입력 ===\n{source}\n=== 입력 끝 ==="
    return {"kind": kind, "target": target, "system": SYSTEM, "prompt": prompt, "source": source, "before": before}


def _build_node(draft: dict, node_id: str | None, style: str) -> dict:
    n = _node(draft, node_id, NODE_TARGETS, "본문 다시 쓰기")
    body = str(n.get("text") or "")
    source = f"제목: {n.get('title') or ''}\n지금 본문: {body.strip() or '(비어 있음)'}"
    kids = _child_lines(draft, n)
    if kids:
        source += "\n켜진 하위 항목:\n" + "\n".join(kids)
    rules = NODE_RULES.format(factor=LENGTH_FACTOR, style=_style(style))
    return _assemble("node", {"id": n["id"], "field": "text"}, rules, source, body)


def _summary_node(draft: dict) -> dict:
    nodes = draft.get("nodes") or {}
    for i in draft.get("root") or []:
        if i in nodes and nodes[i].get("kind") == "summary":
            return nodes[i]
    for n in nodes.values():
        if n.get("kind") == "summary":
            return n
    raise ValueError("요약 노드가 없습니다")


def _build_summary(draft: dict, style: str) -> dict:
    target = _summary_node(draft)
    nodes = draft.get("nodes") or {}
    blocks: list[str] = []
    for pid in draft.get("root") or []:
        p = nodes.get(pid)
        if not p or p.get("kind") != "project" or not p.get("on"):
            continue
        name, lines = p.get("title") or "", []
        for c in _on_children(draft, p):
            if c.get("kind") == "claim":
                body = str(c.get("text") or "").strip()
                lines.append(f"- {name}: {c.get('title') or ''}" + (f" — {body}" if body else ""))
            elif c.get("kind") == "ledger":
                lines += [f"- {name} 결정: {i['text']}" for i in c.get("items") or [] if i.get("kind") == "decision" and i.get("text")]
        if lines:
            blocks.append("\n".join(lines))
    source = "\n".join(blocks) or "(켜진 항목 없음)"
    return _assemble("summary", {"id": target["id"], "field": "text"}, SUMMARY_RULES.format(style=_style(style)), source,
                     str(target.get("text") or ""))


def _parent_claim(draft: dict, rec: dict) -> dict | None:
    return next((n for n in (draft.get("nodes") or {}).values() if n.get("kind") == "claim" and rec.get("id") in (n.get("children") or [])), None)


def _build_caption(draft: dict, node_id: str | None, style: str) -> dict:
    rec = _node(draft, node_id, ("record",), "설명 다시 쓰기")
    now = [str(x) for x in rec.get("caption") or []]
    lines = [f"기록 제목: {_safe_title(rec.get('title'))}"]
    if rec.get("kind_label"):
        lines.append(f"종류: {rec['kind_label']}")
    lines.append("지금 설명: " + (" / ".join(now) if now else "(없음)"))
    claim = _parent_claim(draft, rec)
    if claim:
        lines.append(f"속한 항목 제목: {claim.get('title') or ''}")
        if str(claim.get("text") or "").strip():
            lines.append(f"속한 항목 본문: {claim['text'].strip()}")
    rules = CAPTION_RULES.format(chars=MAX_CAPTION_CHARS, style=_style(style))
    return _assemble("caption", {"id": rec["id"], "field": "caption"}, rules, "\n".join(lines), now)


def build(kind: str, draft: dict, node_id: str | None, style: str = DEFAULT_STYLE) -> dict:
    """{"kind", "target": {"id", "field"}, "system", "prompt", "source", "before"}; ValueError for what an aid cannot target."""
    if kind == "node":
        return _build_node(draft, node_id, style)
    if kind == "summary":
        return _build_summary(draft, style)
    if kind == "caption":
        return _build_caption(draft, node_id, style)
    raise ValueError(f"알 수 없는 보조 종류입니다: {kind}")


def _unfence(answer: str) -> str:
    text = (answer or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    m = _FENCE.search(text)
    if m:
        return m.group(1).strip()
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("```")).strip()


def _lines(text: str) -> list[str]:
    out = []
    for raw in text.split("\n"):
        line = _BULLET.sub("", raw).strip()
        if line:
            out.append(line)
    return out


def parse(kind: str, answer: str, source: str) -> dict:
    """{"ok", "value", "reason"}. Model noise (fences, bullets, empty lines) is cleaned; what cannot be used comes back ok=False."""
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 보조 종류입니다: {kind}")
    text = _unfence(answer)
    if kind == "node":
        value: str | list[str] = text
    elif kind == "summary":
        value = _lines(text)[:MAX_SUMMARY_LINES]
    else:
        value = [l[:MAX_CAPTION_CHARS] for l in _lines(text)[:2]]
    if not value:
        return {"ok": False, "value": value, "reason": "답이 비어 있어 거부했습니다"}
    joined = value if isinstance(value, str) else "\n".join(value)
    missing = _missing_numbers(joined, source)
    if missing:
        return {"ok": False, "value": value, "reason": "입력에 없는 숫자가 있어 거부했습니다: " + ", ".join(missing)}
    return {"ok": True, "value": value, "reason": None}
