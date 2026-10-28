# composer/composer_lib/outline.py
"""The draft tree: built by rule from a week package (v3), edited as an outline, rendered once into blocks.

The home server ships the structure (projects, chapters, records) and, from package_version 9, seeds (summary
lines, captions, flows, a ledger excerpt). The rules here decide what starts on, off or folded; the writer prunes."""
from __future__ import annotations

import hashlib
import re

from .library import short_project

KINDS = ("summary", "project", "claim", "record", "flow", "ledger", "text")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
LEDGER_LABEL = {"decision": "결정", "resolved": "닫힘", "open": "열림", "next": "다음"}


def node_id(week: str, project: str | None, chapter: str | None, record: str | None, kind: str) -> str:
    key = "|".join([week, project or "", chapter or "", record or "", kind])
    return "n-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _node(nid: str, kind: str, title: str, text: str = "", *, on: bool = True, folded: bool = False, src: dict | None = None,
          marks: list[str] | None = None, tier: str = "main", **extra) -> dict:
    return {"id": nid, "kind": kind, "title": title, "text": text, "on": on, "folded": folded, "page": False, "stale": False,
            "src": {"week": None, "project": None, "chapter": None, "record": None, **(src or {})},
            "marks": marks or [], "tier": tier, "children": [], **extra}


def rule_caption(rec: dict) -> list[str]:
    first = str(rec.get("title") or rec.get("id") or "").strip()
    second = str(rec.get("summary") or rec.get("why") or "").strip()
    return [first] + ([second] if second and second != first else [])


def rule_summary(data: dict) -> list[str]:
    lines = []
    for project, p in (data.get("projects") or {}).items():
        if not isinstance(p, dict):
            continue
        titles = [c["title"] for c in p.get("chapters") or [] if isinstance(c, dict) and c.get("title") and (c.get("tier") or "main") == "main"]
        if titles:
            lines.append(f"{short_project(project)}: " + " · ".join(titles[:3]))
        elif p.get("one_line"):
            lines.append(f"{short_project(project)}: {p['one_line']}")
    return lines[:5]


def initial_on(kind: str, ctx: dict) -> tuple[bool, bool]:
    """(on, folded) by the spec's table 4.3. ctx keys by kind: claim: tier, value; record: sent, new, home_core;
    flow: n; ledger: has_decisions, has_open."""
    if kind == "claim":
        if ctx.get("value") == "생략":
            return False, False
        return True, ctx.get("tier") == "appendix"
    if kind == "record":
        if ctx.get("sent") not in ("core", "support"):
            return False, False
        if ctx.get("home_core"):
            return (bool(ctx.get("new")), True)
        return (bool(ctx.get("new")), False)
    if kind == "flow":
        return (ctx.get("n", 0) >= 2, True)
    if kind == "ledger":
        if ctx.get("has_decisions"):
            return True, False
        return (bool(ctx.get("has_open")), True)
    return True, False


def _item_text(x) -> str:
    if isinstance(x, dict):
        x = x.get("text")
    return "" if x is None else str(x)


def _list(x) -> list:
    return x if isinstance(x, list) else []


def _ledger_items(x) -> list[dict]:
    if not isinstance(x, dict):
        return []
    items = []
    for kind, key in (("decision", "decisions"), ("resolved", "resolved"), ("open", "open"), ("next", "next_steps")):
        items += [{"kind": kind, "text": _item_text(v)} for v in _list(x.get(key))]
    return [i for i in items if i["text"]]


def _caption_lines(value) -> list[str] | None:
    """A caption from a seed or from memory: a list of lines, or a bare string (one line); anything else is ignored."""
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list):
        lines = [str(x) for x in value if x is not None and str(x).strip()]
        return lines[:2] or None
    return None


def build_tree(data: dict, week: str, memory: dict | None = None) -> dict:
    memory = memory or {}
    captions, used = memory.get("captions") or {}, memory.get("used") or {}
    try:
        rnd = int(data.get("round") or 1)
    except (TypeError, ValueError):
        rnd = 1
    nodes: dict[str, dict] = {}
    root: list[str] = []

    def add(n: dict) -> str:
        nodes[n["id"]] = n
        return n["id"]

    def used_elsewhere(key: str) -> bool:
        return any(w != week for w in used.get(key) or [])

    outline = data.get("outline") if isinstance(data.get("outline"), dict) else {}
    summary = [str(s) for s in _list(outline.get("summary"))] or rule_summary(data)
    root.append(add(_node(node_id(week, None, None, None, "summary"), "summary", "이번 주 요약", "\n".join(summary), src={"week": week})))
    records = [r for r in data.get("records") or [] if isinstance(r, dict) and r.get("sent") in ("core", "support")]
    for project, p in (data.get("projects") or {}).items():
        if not isinstance(p, dict):
            continue
        short = short_project(project)
        pid = add(_node(node_id(week, project, None, None, "project"), "project", short, str(p.get("overview") or ""), src={"week": week, "project": project}))
        proj = nodes[pid]
        mine = [r for r in records if r.get("project") == project]
        for c in p.get("chapters") or []:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "")
            on, folded = initial_on("claim", {"tier": c.get("tier") or "main", "value": c.get("value")})
            marks = (["changed"] if c.get("change") else []) + (["used"] if used_elsewhere(cid) else [])
            claim = _node(node_id(week, project, cid, None, "claim"), "claim", str(c.get("title") or "(제목 없음)"), str(c.get("lead") or ""),
                          on=on, folded=folded, src={"week": week, "project": project, "chapter": cid}, marks=marks, tier=c.get("tier") or "main")
            proj["children"].append(add(claim))
            for r in mine:
                if r.get("chapter") != cid:
                    continue
                claim["children"].append(add(_record_node(week, project, cid, r, rnd, captions, used_elsewhere)))
            flow = [f for f in c.get("flow") or [] if isinstance(f, dict) and f.get("text")]
            on, folded = initial_on("flow", {"n": len(flow)})
            claim["children"].append(add(_node(node_id(week, project, cid, None, "flow"), "flow", "흐름", "", on=on, folded=folded,
                                               src={"week": week, "project": project, "chapter": cid}, items=flow)))
        loose = [r for r in mine if not r.get("chapter") or r.get("chapter") not in {str(c.get("id")) for c in p.get("chapters") or [] if isinstance(c, dict)}]
        if loose:
            lid = add(_node(node_id(week, project, "loose", None, "claim"), "claim", "정리 단위에 묶이지 않은 결과물", "", folded=True,
                            src={"week": week, "project": project, "chapter": "loose"}, tier="appendix"))
            proj["children"].append(lid)
            for r in loose:
                nodes[lid]["children"].append(add(_record_node(week, project, "loose", r, rnd, captions, used_elsewhere)))
        items = _ledger_items(p.get("ledger"))
        if items:
            on, folded = initial_on("ledger", {"has_decisions": any(i["kind"] in ("decision", "resolved") for i in items),
                                               "has_open": any(i["kind"] in ("open", "next") for i in items)})
            proj["children"].append(add(_node(node_id(week, project, None, None, "ledger"), "ledger", "결정과 열린 것", "", on=on, folded=folded,
                                              src={"week": week, "project": project}, items=items)))
        root.append(pid)
    counts = {"on": sum(1 for n in nodes.values() if n["on"]), "off": sum(1 for n in nodes.values() if not n["on"]), "stale": 0}
    return {"week": week, "round": rnd, "nodes": nodes, "root": root, "counts": counts}


def _record_node(week: str, project: str, cid: str, r: dict, rnd: int, captions: dict, used_elsewhere) -> dict:
    rid = str(r.get("id"))
    files = [f for f in r.get("files") or [] if isinstance(f, dict)]
    home_core = any(f.get("home") and f.get("role") == "core" for f in files)
    new = rnd == 1 or bool(r.get("in_round"))
    on, folded = initial_on("record", {"sent": r.get("sent"), "new": new, "home_core": home_core})
    marks = ["new" if new else "sent"] + (["home"] if home_core else []) + (["used"] if used_elsewhere(rid) else [])
    entry = captions.get(rid)
    caption = _caption_lines(entry.get("text") if isinstance(entry, dict) else entry) or _caption_lines(r.get("caption")) or rule_caption(r)[:2]
    show = "representative" if r.get("representative") else ("core" if r.get("href") else "")
    return _node(node_id(week, project, cid, rid, "record"), "record", str(r.get("title") or rid), "", on=on, folded=folded,
                 src={"week": week, "project": project, "chapter": cid, "record": rid}, marks=marks,
                 caption=caption, show=show, kind_label=str(r.get("kind") or ""), href=r.get("href"), representative=r.get("representative"),
                 files=[{"rel": f.get("rel"), "role": f.get("role"), "href": f.get("href"), "home": bool(f.get("home"))} for f in files])


def _ref(n: dict) -> str | None:
    s = n["src"]
    return None if n["kind"] == "text" else ":".join([s.get("week") or "", s.get("project") or "", s.get("chapter") or "", s.get("record") or ""])


def _kdate(iso: str) -> str:
    m = re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", iso or "")
    return f"{int(m.group(1))}월 {int(m.group(2))}일" if m else iso


def _own_blocks(n: dict, week: str) -> list[dict]:
    """The blocks of one node, without its children."""
    ref, out = _ref(n), []

    def b(k: int, **kw) -> dict:
        return {"id": f"b-{n['id'][2:]}-{k}", "source_ref": ref, **kw}
    kind = n["kind"]
    if kind == "summary":
        out.append(b(0, type="callout", text=n["text"]))
    elif kind == "project":
        out.append(b(0, type="heading", level=2, text=n["title"]))
        if n.get("text"):
            out.append(b(1, type="paragraph", text=n["text"]))
    elif kind == "claim":
        out.append(b(0, type="heading", level=3, text=n["title"]))
        if n.get("text"):
            out.append(b(1, type="paragraph", text=n["text"]))
    elif kind == "record":
        caption = " — ".join(x for x in n.get("caption") or [] if x) or n["title"]
        rep, href = n.get("representative"), n.get("href")
        show = n.get("show") or "representative"
        k = 0
        img = rep if show == "representative" and rep else (href if href and href.lower().endswith(IMAGE_SUFFIXES) else None)
        if show not in ("representative", "core"):                           # a chosen file
            chosen = next((f for f in n.get("files") or [] if f.get("rel") == show and f.get("href")), None)
            img, href = (chosen["href"] if chosen and chosen["href"].lower().endswith(IMAGE_SUFFIXES) else None), (chosen["href"] if chosen else href)
        if img:
            out.append(b(k, type="image", src=f"{week}/{img}", caption=caption)); k += 1
        if href and href != img:
            out.append(b(k, type="file", src=f"{week}/{href}", caption=caption if not img else n["title"])); k += 1
        if not img and not href:
            out.append(b(k, type="paragraph", text=f"{n['title']} (파일은 집에 있음) — {caption}"))
    elif kind == "flow":
        out.append(b(0, type="bullets", items=[f"{_kdate(i.get('when', ''))} · {i.get('text', '')}" for i in n.get("items") or []]))
    elif kind == "ledger":
        out.append(b(0, type="bullets", items=[f"{LEDGER_LABEL.get(i['kind'], i['kind'])}: {i['text']}" for i in n.get("items") or []]))
    elif kind == "text":
        lines = [l for l in (n.get("text") or "").split("\n") if l.strip()]
        if lines and all(l.lstrip().startswith("- ") for l in lines):
            out.append(b(0, type="bullets", items=[l.lstrip()[2:].strip() for l in lines]))
        else:
            out.append(b(0, type="paragraph", text=n.get("text") or ""))
    return out


def to_blocks(draft: dict) -> tuple[list[dict], list[dict]]:
    nodes, week = draft["nodes"], draft.get("week") or ""
    main: list[dict] = []
    reference: list[dict] = []
    pages: list[dict] = []

    def first_sentence(text: str) -> str:
        return re.split(r"(?<=[.!?。])\s", (text or "").strip(), maxsplit=1)[0]

    def walk(nid: str, out: list[dict], in_reference: bool) -> None:
        n = nodes.get(nid)
        if not n or not n.get("on"):
            return
        if n.get("page") and not in_reference:
            own: list[dict] = []
            walk_page(n, own)
            pages.append({"node": n["id"], "title": n["title"], "blocks": own})
            out.append({"id": f"b-{n['id'][2:]}-stub", "type": "paragraph", "source_ref": _ref(n),
                        "text": f"{n['title']} — {first_sentence(n.get('text'))} [[page:{n['id']}]]".replace(" —  [[", " [[")})
            return
        if n.get("folded") and not in_reference:
            walk_into(n, reference, True)
            return
        walk_into(n, out, in_reference)

    def walk_into(n: dict, out: list[dict], in_reference: bool) -> None:
        out.extend(_own_blocks(n, week))
        for c in n.get("children") or []:
            walk(c, out, in_reference)

    def walk_page(n: dict, out: list[dict]) -> None:
        head = _own_blocks(n, week)
        if head and head[0]["type"] == "heading":
            head[0]["level"] = 2
        out.extend(head)
        for c in n.get("children") or []:
            walk(c, out, False)

    for rid in draft.get("root") or []:
        walk(rid, main, False)
    if reference:
        main.append({"id": "b-reference-0", "type": "heading", "level": 2, "text": "참고", "source_ref": None})
        main.extend(reference)
    return main, pages
