"""Drafts: the pages the user assembles. One JSON file per draft under <workspace>/drafts, written atomically."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import secrets
from pathlib import Path

from .outline import KINDS

BLOCK_TYPES = {"heading", "paragraph", "bullets", "image", "file", "divider", "callout", "table", "columns"}


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Drafts:
    def __init__(self, workspace_dir: Path):
        self.dir = Path(workspace_dir) / "drafts"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, draft_id: str) -> Path:
        if not draft_id.startswith("d-") or any(c in draft_id for c in "/\\."):
            raise ValueError("bad draft id")
        return self.dir / f"{draft_id}.json"

    def _write(self, draft: dict) -> dict:
        path = self._path(draft["id"])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return draft

    def list(self) -> list[dict]:
        out = []
        for p in self.dir.glob("d-*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append({"id": d["id"], "title": d.get("title", ""), "updated": d.get("updated"), "created": d.get("created"),
                        "block_count": len(d.get("blocks") or []), "confluence": d.get("confluence"),
                        "kind": d.get("kind") or "blocks", "week": d.get("week")})
        return sorted(out, key=lambda d: d.get("updated") or "", reverse=True)

    def create(self, title: str) -> dict:
        now = _now()
        return self._write({"id": f"d-{secrets.token_hex(6)}", "title": title or "제목 없음", "created": now, "updated": now,
                            "blocks": [], "confluence": None})

    def create_tree(self, title: str, week: str, tree: dict) -> dict:
        now = _now()
        d = {"id": f"d-{secrets.token_hex(6)}", "title": title or "제목 없음", "kind": "tree", "week": week,
             "round": int(tree.get("round") or 1), "created": now, "updated": now,
             "nodes": tree["nodes"], "root": list(tree["root"]), "confluence": None, "pages": {}}
        self._validate_tree(d)
        return self._write(d)

    @staticmethod
    def _validate_tree(d: dict) -> None:
        nodes = d.get("nodes")
        if not isinstance(nodes, dict) or not isinstance(d.get("root"), list):
            raise ValueError("tree draft needs nodes and root")
        for nid, n in nodes.items():
            if not isinstance(n, dict) or n.get("kind") not in KINDS:
                raise ValueError(f"unknown node kind: {n.get('kind') if isinstance(n, dict) else n!r}")
            for c in n.get("children") or []:
                if c not in nodes:
                    raise ValueError(f"child {c} of {nid} is not a node")
        for r in d["root"]:
            if r not in nodes:
                raise ValueError(f"root {r} is not a node")

    def get(self, draft_id: str) -> dict | None:
        p = self._path(draft_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, draft: dict) -> dict:
        if draft.get("kind") == "tree":
            self._validate_tree(draft)
        else:
            for b in draft.get("blocks") or []:
                if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
                    raise ValueError(f"unknown block type: {b.get('type') if isinstance(b, dict) else b!r}")
        existing = self.get(draft["id"]) or {}
        merged = {**existing, **draft, "updated": _now()}
        merged.setdefault("created", merged["updated"])
        merged.setdefault("confluence", None)
        return self._write(merged)

    def duplicate(self, draft_id: str) -> dict:
        src = self.get(draft_id)
        if src is None:
            raise KeyError(draft_id)
        now = _now()
        copy_ = copy.deepcopy(src)
        copy_.update({"id": f"d-{secrets.token_hex(6)}", "title": f"{src.get('title', '')} (복사본)", "created": now, "updated": now, "confluence": None})
        return self._write(copy_)

    def delete(self, draft_id: str) -> None:
        p = self._path(draft_id)
        if p.exists():
            p.unlink()
