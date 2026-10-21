"""Library: turn extracted week packages into reusable blocks with stable ids.

Block ids are `<week>:<short>:<stream_index>:<type>:<n>`; `src` paths are relative to the weeks dir so the
server can serve them under /files/. Week-level assets (README, weekly.md, assets/*) sit beside the streams.
"""
from __future__ import annotations

import json
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


def _week_entry(weeks_dir: Path, week_dir: Path) -> dict:
    week = week_dir.name
    entry = {"week": week, "since": None, "until": None, "projects": [], "assets": []}
    meta_path = week_dir / "outcomes.json"
    data = None
    if meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            data = None
    if data:
        entry["since"], entry["until"] = data.get("since"), data.get("until")
        for project, p in (data.get("projects") or {}).items():
            short = short_project(project)
            evidence = {e["n"]: e for e in p.get("evidence") or [] if isinstance(e, dict) and "n" in e}
            streams = []
            for i, s in enumerate(p.get("streams") or []):
                streams.append({"id": f"{week}:{short}:{i}", "title": s.get("title") or "(제목 없음)", "status": s.get("status") or "",
                                "blocks": _stream_blocks(weeks_dir, week_dir, week, short, i, s, evidence)})
            entry["projects"].append({"project": project, "short": short, "streams": streams})
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
            for s in p["streams"]:
                for b in s["blocks"]:
                    if b["id"] == block_id:
                        return b
    return None
