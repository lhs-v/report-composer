# composer/composer_lib/outline.py
"""The draft tree: built by rule from a week package (v3), edited as an outline, rendered once into blocks.

The home server ships the structure (projects, chapters, records) and, from package_version 9, seeds (summary
lines, captions, flows, a ledger excerpt). The rules here decide what starts on, off or folded; the writer prunes."""
from __future__ import annotations

import hashlib

from .library import short_project

KINDS = ("summary", "project", "claim", "record", "flow", "ledger", "text")


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
            return True, True
        return (bool(ctx.get("new")), False)
    if kind == "flow":
        return (ctx.get("n", 0) >= 2, True)
    if kind == "ledger":
        if ctx.get("has_decisions"):
            return True, False
        return (bool(ctx.get("has_open")), True)
    return True, False


def _ledger_items(x: dict | None) -> list[dict]:
    if not x:
        return []
    items = [{"kind": "decision", "text": d} for d in x.get("decisions") or []]
    items += [{"kind": "resolved", "text": r} for r in x.get("resolved") or []]
    items += [{"kind": "open", "text": o.get("text", "") if isinstance(o, dict) else str(o)} for o in x.get("open") or []]
    items += [{"kind": "next", "text": s.get("text", "") if isinstance(s, dict) else str(s)} for s in x.get("next_steps") or []]
    return [i for i in items if i["text"]]


def build_tree(data: dict, week: str, memory: dict | None = None) -> dict:
    memory = memory or {}
    captions, used = memory.get("captions") or {}, memory.get("used") or {}
    rnd = int(data.get("round") or 1)
    nodes: dict[str, dict] = {}
    root: list[str] = []

    def add(n: dict) -> str:
        nodes[n["id"]] = n
        return n["id"]

    def used_elsewhere(key: str) -> bool:
        return any(w != week for w in used.get(key) or [])

    summary = [str(s) for s in ((data.get("outline") or {}).get("summary") or [])] or rule_summary(data)
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
    remembered = (captions.get(rid) or {}).get("text")
    caption = [str(x) for x in (remembered or r.get("caption") or rule_caption(r))][:2]
    show = "representative" if r.get("representative") else ("core" if r.get("href") else "")
    return _node(node_id(week, project, cid, rid, "record"), "record", str(r.get("title") or rid), "", on=on, folded=folded,
                 src={"week": week, "project": project, "chapter": cid, "record": rid}, marks=marks,
                 caption=caption, show=show, kind_label=str(r.get("kind") or ""), href=r.get("href"), representative=r.get("representative"),
                 files=[{"rel": f.get("rel"), "role": f.get("role"), "href": f.get("href"), "home": bool(f.get("home"))} for f in files])
