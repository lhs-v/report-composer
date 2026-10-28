"""What the company PC remembers between weeks: captions the writer fixed, and which records and chapters each
exported draft used. There is no way back home, so this file is the only place these live."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path


def _empty() -> dict:
    return {"captions": {}, "used": {}}


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty()
        if not isinstance(raw, dict):
            return _empty()
        captions, used = raw.get("captions"), raw.get("used")
        return {"captions": dict(captions) if isinstance(captions, dict) else {},
                "used": dict(used) if isinstance(used, dict) else {}}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def data(self) -> dict:
        return {"captions": dict(self._data["captions"]), "used": {k: list(v) for k, v in self._data["used"].items()}}

    def caption(self, rid: str) -> list[str] | None:
        entry = self._data["captions"].get(rid)
        return list(entry["text"]) if isinstance(entry, dict) and entry.get("text") else None

    def set_caption(self, rid: str, text: list[str], week: str) -> None:
        self._data["captions"][rid] = {"text": [str(x) for x in text][:2], "week": week,
                                       "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        self._write()

    def mark_used(self, ids: list[str], week: str) -> None:
        for i in ids:
            weeks = self._data["used"].setdefault(i, [])
            if week not in weeks:
                weeks.append(week)
                weeks.sort()
        self._write()

    def weeks_used(self, key: str) -> list[str]:
        return list(self._data["used"].get(key) or [])
