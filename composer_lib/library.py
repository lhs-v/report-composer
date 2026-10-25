"""Library: turn extracted week packages into reusable blocks with stable ids.

v1 packages (`streams`, no `schema`): block ids are `<week>:<short>:<stream_index>:<type>:<n>`.
v2 packages (`"schema": 2`, `chapters`, see docs/package-format-v2.md): one library stream per chapter, block ids
`<week>:<short>:<chapter id>:<type>:<n>`, result files found only through `evidence[].package`.
v3 packages (`"schema": 3`, `records`, see docs/package-format-v3.md): the chapters frame the page as in v2, but
the results are the records: block ids `<week>:<short>:<chapter id|loose>:<R-id>:<type>:<n>`, files found through
`records[].files[].href`. A record whose folder has not arrived (its part mail is still on the way) is listed as
missing; a file that stayed home is named, not a block.
`src` paths are relative to the weeks dir so the server can serve them under /files/. Week-level assets
(README, weekly.md, assets/*) sit beside the streams.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LABELS = (("problem", "무엇을 풀려고 했나"), ("approach", "어떻게 접근했나"))
TAIL_LABELS = (("status", "지금 어디까지"), ("next", "다음"))
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
TEXT_SUFFIXES = (".md", ".txt")


def short_project(name: str) -> str:
    for prefix in ("C--Claude-", "C--Users-ruee1-"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _rel(weeks_dir: Path, p: Path) -> str:
    return p.relative_to(weeks_dir).as_posix()


def _read_text(p: Path, limit: int = 200_000) -> str:
    try:
        return p.read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeDecodeError):
        return ""


def _asset_block(weeks_dir: Path, p: Path, bid: str, caption: str | None = None, **extra) -> dict:
    suf = p.suffix.lower()
    if suf in IMAGE_SUFFIXES:
        kind = "image"
    elif suf in TEXT_SUFFIXES:
        kind = "markdown"
    elif p.name == "index.html" or suf in (".html", ".htm"):
        kind = "page"
    else:
        kind = "file"
    block = {"id": bid, "type": kind, "src": _rel(weeks_dir, p), "caption": caption or p.name, "size": p.stat().st_size, **extra}
    if kind == "markdown":
        block["text"] = _read_text(p)
    return block


def _stream_blocks(weeks_dir: Path, week_dir: Path, week: str, short: str, i: int, stream: dict, evidence: dict[int, dict]) -> list[dict]:
    blocks: list[dict] = []
    meta = {"week": week, "project": short, "stream": i}
    counters: dict[str, int] = {}

    def bid(kind: str) -> str:
        n = counters.get(kind, 0)
        counters[kind] = n + 1
        return f"{week}:{short}:{i}:{kind}:{n}"

    blocks.append({"id": bid("heading"), "type": "heading", "level": 2, "text": stream.get("title") or "(제목 없음)", **meta})
    for key, label in LABELS:
        if stream.get(key):
            blocks.append({"id": bid("paragraph"), "type": "paragraph", "label": label, "text": stream[key], **meta})
    referenced: list[int] = []
    for r in stream.get("results") or []:
        if isinstance(r, dict):
            blocks.append({"id": bid("bullet"), "type": "bullet", "text": r.get("text", ""), "evidence": list(r.get("evidence") or []), **meta})
            referenced += [n for n in r.get("evidence") or [] if n not in referenced]
    for key, label in TAIL_LABELS:
        if stream.get(key):
            blocks.append({"id": bid("paragraph"), "type": "paragraph", "label": label, "text": stream[key], **meta})

    pages_dir = week_dir / "pages"
    for n in referenced:
        ev = evidence.get(n)
        if not ev:
            continue
        folder = next((d for d in sorted(pages_dir.iterdir()) if d.is_dir() and d.name.startswith(f"{short}-{n:02d}")), None) if pages_dir.exists() else None
        if folder is None:
            continue
        preview = folder / "preview.png"
        if preview.is_file():
            blocks.append(_asset_block(weeks_dir, preview, bid("image"), caption=ev.get("title") or preview.name, evidence_n=n, **meta))
        index = folder / "index.html"
        if index.is_file():
            blocks.append(_asset_block(weeks_dir, index, bid("page"), caption=ev.get("title") or "결과 페이지", evidence_n=n, **meta))
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.name not in ("preview.png", "index.html"):
                blocks.append(_asset_block(weeks_dir, f, bid("file"), caption=f"{ev.get('title') or ''} · {f.name}".strip(" ·"), evidence_n=n, **meta))

    for md in sorted(week_dir.glob(f"{short}-{i + 1:02d}*.md")):
        blocks.append(_asset_block(weeks_dir, md, bid("markdown"), caption=md.name, **meta))
    return blocks


def _v1_project(weeks_dir: Path, week_dir: Path, week: str, project: str, p: dict) -> dict:
    short = short_project(project)
    evidence = {e["n"]: e for e in p.get("evidence") or [] if isinstance(e, dict) and "n" in e}
    streams = []
    for i, s in enumerate(p.get("streams") or []):
        streams.append({"id": f"{week}:{short}:{i}", "title": s.get("title") or "(제목 없음)", "status": s.get("status") or "",
                        "blocks": _stream_blocks(weeks_dir, week_dir, week, short, i, s, evidence)})
    return {"project": project, "short": short, "streams": streams}


# ---------- v2 (chapters) ----------
CHAPTER_META = ("kind", "value", "tier", "section", "label", "lead", "change")
DAILY_ID = "units"   # pseudo chapter id for the one stream of a daily_list project


def _pkg_file(week_dir: Path, rel) -> Path | None:
    """A package-relative path from evidence[].package, only if it stays inside the week folder and exists."""
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        return None
    norm = rel.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in norm.split("/"):
        return None
    p = week_dir / norm
    try:
        p.resolve().relative_to(week_dir.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def _chapter_mds(week_dir: Path, short: str) -> dict[int, list[Path]]:
    """`<short>-<nn>-<slug>.md` files keyed by nn (the chapter's 1-based order inside its project)."""
    pat = re.compile(rf"{re.escape(short)}-(\d+)(?:-.*)?\.md")
    out: dict[int, list[Path]] = {}
    for p in sorted(week_dir.glob(f"{short}-*.md")):
        m = pat.fullmatch(p.name)
        if m and p.is_file():
            out.setdefault(int(m.group(1)), []).append(p)
    return out


def _chapter_md(week_dir: Path, short: str, nn: int, ch: dict, by_nn: dict[int, list[Path]]) -> list[Path]:
    """The chapter's md file: the name the package records (`md`), else the writer's naming rule, else the newest
    file with that number. Re-received weeks keep old files beside new ones, so the number alone is not enough."""
    named = _pkg_file(week_dir, ch.get("md"))
    if named and named.suffix.lower() == ".md":
        return [named]
    found = by_nn.get(nn, [])
    if len(found) <= 1:
        return found
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(ch.get("label") or ch.get("title") or "")).strip("-")[:24]
    exact = week_dir / (f"{short}-{nn:02d}-{slug}.md" if slug else f"{short}-{nn:02d}.md")
    if exact in found:
        return [exact]
    return [max(found, key=lambda p: p.stat().st_mtime)]


def _units_text(units) -> str:
    lines = []
    for u in units or []:
        if isinstance(u, dict):
            line = " · ".join(x for x in (str(u.get("when") or "").strip(), str(u.get("line") or "").strip()) if x)
            if line:
                lines.append(line)
    return "\n".join(lines)


def _result_blocks(weeks_dir: Path, week_dir: Path, ev: dict, pos: int, prefix: str, meta: dict) -> list[dict]:
    """Blocks for one result found through evidence[].package. Ids carry the result's position, not a running
    count, so a result that loses its copy does not shift the ids of the ones after it."""
    pkg = ev.get("package")
    if not isinstance(pkg, dict):
        return []        # no copy in this package (a commit, or a copy that was missing)
    title = ev.get("title") or ""
    rmeta = {"eid": ev.get("eid"), "evidence_kind": ev.get("kind"), **meta}
    blocks = []
    preview = _pkg_file(week_dir, pkg.get("thumb")) or _pkg_file(week_dir, pkg.get("preview"))   # the first screen when cut
    if preview:
        blocks.append(_asset_block(weeks_dir, preview, f"{prefix}:image:{pos}", caption=title or preview.name, **rmeta))
    href = _pkg_file(week_dir, pkg.get("href"))
    if href:
        suf = href.suffix.lower()
        kind = ("page" if suf in (".html", ".htm") else "markdown" if suf in TEXT_SUFFIXES
                else "image" if suf in IMAGE_SUFFIXES else "file")
        if not (kind == "image" and preview and href == preview):
            cap = title or ("결과 페이지" if kind == "page" else href.name)
            blocks.append(_asset_block(weeks_dir, href, f"{prefix}:{kind}:{pos}", caption=cap, **rmeta))
    files = pkg.get("files") if isinstance(pkg.get("files"), list) else []
    for k, rel in enumerate(files):
        f = _pkg_file(week_dir, rel)
        if f and f != preview and f != href:
            kind = "image" if f.suffix.lower() in IMAGE_SUFFIXES else "file"
            # files a page carries (its audio, figures, video posters): folded under the page, not part of
            # "흐름 전체 추가"; the page itself is where they are read and picked
            blocks.append(_asset_block(weeks_dir, f, f"{prefix}:{kind}:{pos}-{k}", caption=f"{title} · {f.name}".strip(" ·"),
                                       in_page=True, optional=True, **rmeta))
    return blocks


CID_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")


def _chapter_blocks(weeks_dir: Path, week_dir: Path, week: str, short: str, i: int, cid: str, ch: dict,
                    evidence: dict[str, dict], mds: list[Path]) -> list[dict]:
    """Block ids name the block's role (heading, lead, change, units) or its position among the chapter's own
    sentences and results, so rebuilding the week with one more lead or one less copy keeps the other ids."""
    meta = {"week": week, "project": short, "stream": i, "chapter": cid}
    prefix = f"{week}:{short}:{cid}"
    blocks: list[dict] = [{"id": f"{prefix}:heading:0", "type": "heading", "level": 2, "text": ch.get("title") or "(제목 없음)", **meta}]
    if ch.get("lead"):
        blocks.append({"id": f"{prefix}:lead:0", "type": "paragraph", "label": "요약", "text": ch["lead"], "role": "lead", **meta})
    for k, s in enumerate(ch.get("sentences") or []):
        if isinstance(s, dict) and s.get("text"):
            blocks.append({"id": f"{prefix}:bullet:{k}", "type": "bullet", "text": s["text"], "unit": s.get("unit"), **meta})
    for pos, eid in enumerate(ch.get("results") or []):
        if isinstance(eid, str) and isinstance(evidence.get(eid), dict):
            blocks += _result_blocks(weeks_dir, week_dir, evidence[eid], pos, prefix, meta)
    if ch.get("change"):
        blocks.append({"id": f"{prefix}:change:0", "type": "paragraph", "label": "지난주 대비", "text": ch["change"], "optional": True,
                       "role": "change", **meta})
    units_text = _units_text(ch.get("units"))
    if units_text:
        blocks.append({"id": f"{prefix}:units:0", "type": "paragraph", "label": "근거 작업 단위", "text": units_text, "optional": True,
                       "role": "units", "units": [u.get("id") for u in ch.get("units") or [] if isinstance(u, dict)], **meta})
    for k, md in enumerate(mds):
        blocks.append(_asset_block(weeks_dir, md, f"{prefix}:md:{k}", caption=md.name, **meta))   # apart from .md results
    return blocks


def _v2_project(weeks_dir: Path, week_dir: Path, week: str, project: str, p: dict) -> dict:
    short = short_project(project)
    mode = p.get("mode") or "chapters"
    entry = {"project": project, "short": short, "schema": 2, "mode": mode,
             "overview": p.get("overview") or "", "one_line": p.get("one_line") or "", "streams": [], "blocks": []}
    pmeta = {"week": week, "project": short}
    # the project's own sentences are blocks too, so they can be picked like any other piece
    if entry["overview"]:
        entry["blocks"].append({"id": f"{week}:{short}:overview:paragraph:0", "type": "paragraph", "label": "개요",
                                "text": entry["overview"], "role": "overview", **pmeta})
    if mode == "one_line" and entry["one_line"]:
        entry["blocks"].append({"id": f"{week}:{short}:one_line:paragraph:0", "type": "paragraph", "text": entry["one_line"],
                                "role": "one_line", **pmeta})
    evidence = {e["eid"]: e for e in p.get("evidence") or [] if isinstance(e, dict) and isinstance(e.get("eid"), str)}
    if mode == "one_line":                                  # its copies are pickable beside the sentence
        for pos, ev in enumerate(evidence.values()):
            entry["blocks"] += _result_blocks(weeks_dir, week_dir, ev, pos, f"{week}:{short}:one_line", pmeta)
        return entry
    if mode == "daily_list":
        meta = {**pmeta, "stream": 0, "chapter": DAILY_ID}
        prefix = f"{week}:{short}:{DAILY_ID}"
        blocks = []
        for k, u in enumerate(p.get("units") or []):
            text = _units_text([u])
            if text:
                blocks.append({"id": f"{prefix}:bullet:{k}", "type": "bullet", "text": text, "unit": u.get("id"), **meta})
        for pos, ev in enumerate(evidence.values()):       # copies the package carries even without chapters
            blocks += _result_blocks(weeks_dir, week_dir, ev, pos, prefix, meta)
        entry["streams"].append({"id": prefix, "chapter": DAILY_ID, "title": "작업 단위 목록",
                                 "status": "", "kind": "", "value": "", "tier": "main", "section": "", "label": "",
                                 "lead": "", "change": "", "blocks": blocks})
        return entry
    loose = {u.get("id") for u in p.get("units") or [] if isinstance(u, dict) and not u.get("chapter")}
    for pos, ev in enumerate(evidence.values()):            # copies of units no chapter took
        if ev.get("unit") in loose:
            entry["blocks"] += _result_blocks(weeks_dir, week_dir, ev, pos, f"{week}:{short}:loose", pmeta)
    by_nn = _chapter_mds(week_dir, short)
    seen: set[str] = set()
    for i, ch in enumerate(c for c in p.get("chapters") or [] if isinstance(c, dict)):
        raw = str(ch.get("id") or "")
        cid = raw if CID_RE.fullmatch(raw) else f"C-{i}"    # ids go into block ids and HTML attributes
        if cid in seen:
            cid = f"{cid}-{i}"
        seen.add(cid)
        stream = {"id": f"{week}:{short}:{cid}", "chapter": cid, "title": ch.get("title") or "(제목 없음)", "status": ""}
        stream.update({k: str(ch.get(k) or "") for k in CHAPTER_META})
        stream["tier"] = stream["tier"] or "main"
        stream["blocks"] = _chapter_blocks(weeks_dir, week_dir, week, short, i, cid, ch, evidence,
                                           _chapter_md(week_dir, short, i + 1, ch, by_nn))
        entry["streams"].append(stream)
    return entry


# ---------- v3 (records) ----------
THUMB_NAMES = ("preview.png", "preview-top.png")


def _kind_of(p: Path) -> str:
    suf = p.suffix.lower()
    if suf in IMAGE_SUFFIXES:
        return "image"
    if suf in TEXT_SUFFIXES:
        return "markdown"
    if suf in (".html", ".htm"):
        return "page"
    return "file"


def _record_blocks(weeks_dir: Path, week_dir: Path, r: dict, prefix: str, meta: dict) -> list[dict]:
    """Blocks of one record: its representative picture, the file a reader opens, then the other files that
    travelled (folded as page files). Ids count per type inside the record, so a missing copy elsewhere never
    shifts them; a record whose folder has not arrived gives no blocks."""
    rmeta = {"record": r.get("id"), **meta}
    title = r.get("title") or r.get("id") or ""
    counters: dict[str, int] = {}

    def bid(kind: str) -> str:
        n = counters.get(kind, 0)
        counters[kind] = n + 1
        return f"{prefix}:{kind}:{n}"
    blocks: list[dict] = []
    rep = _pkg_file(week_dir, r.get("representative"))
    if rep:
        blocks.append(_asset_block(weeks_dir, rep, bid("image"), caption=title, **rmeta))
    main = _pkg_file(week_dir, r.get("href"))
    if main and main != rep:
        kind = _kind_of(main)
        blocks.append(_asset_block(weeks_dir, main, bid(kind), caption=title if kind != "file" else f"{title} · {main.name}", **rmeta))
    for fl in r.get("files") or []:
        if not isinstance(fl, dict) or not fl.get("href"):
            continue
        p = _pkg_file(week_dir, fl["href"])
        if not p or p in (rep, main) or p.name in THUMB_NAMES or p.name.endswith(".poster.jpg"):
            continue
        blocks.append(_asset_block(weeks_dir, p, bid(_kind_of(p)), caption=f"{title} · {p.name}", in_page=True, optional=True, **rmeta))
    return blocks


def _text_blocks(weeks_dir: Path, week_dir: Path, ch: dict, evidence: dict[str, dict], prefix: str, meta: dict) -> list[dict]:
    """Reply excerpts a chapter cites (E-t…): `<prefix>:text:<pos>`, pos being the place in the chapter's results."""
    blocks = []
    for pos, eid in enumerate(ch.get("results") or []):
        ev = evidence.get(eid) if isinstance(eid, str) and eid.startswith("E-t") else None
        href = _pkg_file(week_dir, ((ev or {}).get("package") or {}).get("href")) if ev else None
        if href:
            blocks.append(_asset_block(weeks_dir, href, f"{prefix}:text:{pos}", caption=ev.get("title") or href.name, eid=eid,
                                       evidence_kind="text", **meta))
    return blocks


def _record_row(week_dir: Path, r: dict) -> dict:
    files = [fl for fl in r.get("files") or [] if isinstance(fl, dict)]
    sent = [fl for fl in files if fl.get("href")]
    arrived = r.get("sent") == "core" and bool(sent) and any(_pkg_file(week_dir, fl["href"]) for fl in sent)
    return {"id": r.get("id"), "title": r.get("title") or r.get("id"), "kind": r.get("kind"), "chapter": r.get("chapter"),
            "sent": r.get("sent"), "why": r.get("why") or "", "arrived": arrived, "href": r.get("href"),
            "home": [fl.get("rel") for fl in files if fl.get("home")], "home_bytes": r.get("home_bytes") or 0}


def _v3_project(weeks_dir: Path, week_dir: Path, week: str, project: str, p: dict, records: list[dict]) -> dict:
    short = short_project(project)
    mode = p.get("mode") or "chapters"
    entry = {"project": project, "short": short, "schema": 3, "mode": mode,
             "overview": p.get("overview") or "", "one_line": p.get("one_line") or "", "streams": [], "blocks": [], "records": []}
    pmeta = {"week": week, "project": short}
    if entry["overview"]:
        entry["blocks"].append({"id": f"{week}:{short}:overview:paragraph:0", "type": "paragraph", "label": "개요",
                                "text": entry["overview"], "role": "overview", **pmeta})
    if mode == "one_line" and entry["one_line"]:
        entry["blocks"].append({"id": f"{week}:{short}:one_line:paragraph:0", "type": "paragraph", "text": entry["one_line"],
                                "role": "one_line", **pmeta})
    mine = [r for r in records if isinstance(r, dict) and r.get("project") == project]
    entry["records"] = [_record_row(week_dir, r) for r in mine]
    evidence = {e["eid"]: e for e in p.get("evidence") or [] if isinstance(e, dict) and isinstance(e.get("eid"), str)}
    chapter_ids: set[str] = set()
    streams = []
    if mode == "chapters":
        by_nn = _chapter_mds(week_dir, short)
        seen: set[str] = set()
        for i, ch in enumerate(c for c in p.get("chapters") or [] if isinstance(c, dict)):
            raw = str(ch.get("id") or "")
            cid = raw if CID_RE.fullmatch(raw) else f"C-{i}"
            if cid in seen:
                cid = f"{cid}-{i}"
            seen.add(cid)
            chapter_ids.add(raw)
            meta = {"week": week, "project": short, "stream": i, "chapter": cid}
            prefix = f"{week}:{short}:{cid}"
            blocks: list[dict] = [{"id": f"{prefix}:heading:0", "type": "heading", "level": 2, "text": ch.get("title") or "(제목 없음)", **meta}]
            if ch.get("lead"):
                blocks.append({"id": f"{prefix}:lead:0", "type": "paragraph", "label": "요약", "text": ch["lead"], "role": "lead", **meta})
            for k, s in enumerate(ch.get("sentences") or []):
                if isinstance(s, dict) and s.get("text"):
                    blocks.append({"id": f"{prefix}:bullet:{k}", "type": "bullet", "text": s["text"], "unit": s.get("unit"), **meta})
            home = []
            for r in mine:
                if r.get("chapter") == raw and r.get("sent") == "core":
                    blocks += _record_blocks(weeks_dir, week_dir, r, f"{prefix}:{r['id']}", meta)
                    rels = [fl.get("rel") for fl in r.get("files") or [] if isinstance(fl, dict) and fl.get("home")]
                    if rels:
                        home.append({"record": r["id"], "title": r.get("title") or r["id"], "files": rels, "bytes": r.get("home_bytes") or 0})
            blocks += _text_blocks(weeks_dir, week_dir, ch, evidence, prefix, meta)
            if ch.get("change"):
                blocks.append({"id": f"{prefix}:change:0", "type": "paragraph", "label": "지난주 대비", "text": ch["change"], "optional": True,
                               "role": "change", **meta})
            units_text = _units_text(ch.get("units"))
            if units_text:
                blocks.append({"id": f"{prefix}:units:0", "type": "paragraph", "label": "근거 작업 단위", "text": units_text, "optional": True,
                               "role": "units", "units": [u.get("id") for u in ch.get("units") or [] if isinstance(u, dict)], **meta})
            for k, md in enumerate(_chapter_md(week_dir, short, i + 1, ch, by_nn)):
                blocks.append(_asset_block(weeks_dir, md, f"{prefix}:md:{k}", caption=md.name, **meta))
            stream = {"id": prefix, "chapter": cid, "title": ch.get("title") or "(제목 없음)", "status": "", "home": home}
            stream.update({k: str(ch.get(k) or "") for k in CHAPTER_META})
            stream["tier"] = stream["tier"] or "main"
            stream["blocks"] = blocks
            streams.append(stream)
    elif mode == "daily_list":
        meta = {**pmeta, "stream": 0, "chapter": DAILY_ID}
        prefix = f"{week}:{short}:{DAILY_ID}"
        blocks = []
        for k, u in enumerate(p.get("units") or []):
            text = _units_text([u])
            if text:
                blocks.append({"id": f"{prefix}:bullet:{k}", "type": "bullet", "text": text, "unit": u.get("id"), **meta})
        streams.append({"id": prefix, "chapter": DAILY_ID, "title": "작업 단위 목록", "status": "", "kind": "", "value": "", "tier": "main",
                        "section": "", "label": "", "lead": "", "change": "", "home": [], "blocks": blocks})
    entry["streams"] = streams
    for r in mine:                                   # records no chapter cites (every record before the weekly run)
        if r.get("sent") == "core" and (not r.get("chapter") or r.get("chapter") not in chapter_ids):
            entry["blocks"] += _record_blocks(weeks_dir, week_dir, r, f"{week}:{short}:loose:{r['id']}", pmeta)
    return entry


def _week_entry(weeks_dir: Path, week_dir: Path) -> dict:
    week = week_dir.name
    entry = {"week": week, "since": None, "until": None, "schema": 1, "projects": [], "assets": []}
    meta_path = week_dir / "outcomes.json"
    data = None
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            data = None
    if not isinstance(data, dict):
        data = None
    if data:
        schema = data.get("schema") if isinstance(data.get("schema"), int) else 1
        v2 = schema >= 2
        v3 = schema >= 3 and isinstance(data.get("records"), list)
        entry["since"], entry["until"] = data.get("since"), data.get("until")
        entry["schema"] = 3 if v3 else 2 if v2 else 1
        if schema > 3:
            entry["warning"] = f"이 컴포저가 모르는 패키지 형식(v{schema})입니다. v{3 if v3 else 2}로 읽었으니 빠진 내용이 있을 수 있습니다."
        records = data.get("records") if v3 else []
        for project, p in (data.get("projects") or {}).items():
            if not isinstance(p, dict):
                continue
            try:
                if v3:
                    entry["projects"].append(_v3_project(weeks_dir, week_dir, week, project, p, records))
                else:
                    entry["projects"].append((_v2_project if v2 else _v1_project)(weeks_dir, week_dir, week, project, p))
            except Exception as e:      # one malformed project must not take the whole library down
                entry["projects"].append({"project": project, "short": short_project(project), "schema": entry["schema"],
                                          "mode": "error", "streams": [], "blocks": [], "error": f"{type(e).__name__}: {e}"})
    if entry["schema"] == 3:                       # records whose part mail has not arrived yet
        entry["missing"] = [{"project": pr["short"], "id": r["id"], "title": r["title"]}
                            for pr in entry["projects"] for r in pr.get("records") or [] if r.get("sent") == "core" and not r.get("arrived")]
    n = 0
    for p in sorted(week_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and (not data or not any(p.name.startswith(f"{pr['short']}-") for pr in entry["projects"])):
            entry["assets"].append(_asset_block(weeks_dir, p, f"{week}:_:_:markdown:{n}", week=week))
            n += 1
    assets_dir = week_dir / "assets"
    if assets_dir.is_dir():
        for p in sorted(assets_dir.rglob("*")):
            if p.is_file():
                entry["assets"].append(_asset_block(weeks_dir, p, f"{week}:_:_:asset:{n}", week=week))
                n += 1
    return entry


def build_library(weeks_dir: Path) -> list[dict]:
    weeks_dir = Path(weeks_dir)
    if not weeks_dir.exists():
        return []
    return [_week_entry(weeks_dir, d) for d in sorted((p for p in weeks_dir.iterdir() if p.is_dir()), reverse=True)]


def find_block(weeks_dir: Path, block_id: str) -> dict | None:
    week = block_id.split(":", 1)[0]
    for entry in build_library(weeks_dir):
        if entry["week"] != week:
            continue
        for a in entry["assets"]:
            if a["id"] == block_id:
                return a
        for p in entry["projects"]:
            for b in p.get("blocks") or []:
                if b["id"] == block_id:
                    return b
            for s in p["streams"]:
                for b in s["blocks"]:
                    if b["id"] == block_id:
                        return b
    return None
