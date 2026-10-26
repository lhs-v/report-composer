"""Inbox: collect the mailed zips of a week, extract each as it arrives (a v3 part holds whole records, so what has
come can be read at once), move it to done/, and remember in weeks/<week>/.inbox.json which parts have been seen so
the missing ones stay visible until they come.

File names come from the server's mail.py: <week>.zip (full), <week>-light.zip, <week>-part<i>of<n>.zip; a later
round of the same week is <week>-r<k>-… and its members start with "<week>-r<k>/". Every round merges by plain
overwrite into the one week folder; each round waits on its own parts.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

NAME_RE = re.compile(r"^(?P<week>\d{4}-W\d{2})(?:-r(?P<r>\d+))?(?:-(?P<kind>light|part(?P<i>\d+)of(?P<n>\d+)))?\.zip$")


@dataclass
class InboxState:
    week: str
    round: int = 1
    full: Path | None = None
    light: Path | None = None
    parts: dict[int, Path] = field(default_factory=dict)
    n_parts: int | None = None
    extracted: set = field(default_factory=set)      # part numbers already extracted into the workspace
    extracted_full: bool = False

    @property
    def have(self) -> set:
        return set(self.parts) | set(self.extracted)

    @property
    def missing_parts(self) -> list[int]:
        if self.n_parts is None:
            return []
        return [i for i in range(1, self.n_parts + 1) if i not in self.have]

    @property
    def complete(self) -> bool:
        if self.full is not None or self.extracted_full:
            return True
        return self.n_parts is not None and not self.missing_parts

    def zips(self) -> list[Path]:
        """Extraction order: light first (text), then full, then parts in order; later files overwrite earlier."""
        out = [p for p in (self.light, self.full) if p]
        out += [self.parts[i] for i in sorted(self.parts)]
        return out

    @property
    def key(self) -> str:
        return self.week if self.round == 1 else f"{self.week}-r{self.round}"

    @property
    def prefixes(self) -> tuple[str, ...]:
        return (self.week, f"{self.week}-r{self.round}")

    def summary(self) -> dict:
        return {"week": self.week, "round": self.round, "key": self.key, "complete": self.complete, "has_full": self.full is not None or self.extracted_full,
                "has_light": self.light is not None, "parts": sorted(self.have), "n_parts": self.n_parts, "missing_parts": self.missing_parts}


def _marker(workspace_dir: Path, week: str, round: int = 1) -> Path:
    return Path(workspace_dir) / "weeks" / week / (".inbox.json" if round == 1 else f".inbox-r{round}.json")


def _read_marker(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def scan(inbox_dir: Path, workspace_dir: Path | None = None) -> dict[str, InboxState]:
    """Weeks with zips in the inbox, plus (with `workspace_dir`) weeks extracted in part whose other parts have
    not come: both show as waiting. A week that is complete and extracted is not listed."""
    inbox_dir = Path(inbox_dir)
    states: dict[str, InboxState] = {}
    if inbox_dir.exists():
        for p in sorted(inbox_dir.glob("*.zip")):
            m = NAME_RE.match(p.name)
            if not m:
                continue
            rnd = int(m["r"]) if m["r"] else 1
            key = m["week"] if rnd == 1 else f"{m['week']}-r{rnd}"
            st = states.setdefault(key, InboxState(week=m["week"], round=rnd))
            kind = m["kind"]
            if kind is None:
                st.full = p
            elif kind == "light":
                st.light = p
            else:
                st.parts[int(m["i"])] = p
                st.n_parts = int(m["n"])
    if workspace_dir is not None and (Path(workspace_dir) / "weeks").is_dir():
        for marker in sorted((Path(workspace_dir) / "weeks").glob("*/.inbox*.json")):
            week = marker.parent.name
            m = re.fullmatch(r"\.inbox(?:-r(\d+))?\.json", marker.name)
            rnd = int(m.group(1)) if m and m.group(1) else 1
            key = week if rnd == 1 else f"{week}-r{rnd}"
            data = _read_marker(marker)
            st = states.get(key) or InboxState(week=week, round=rnd)
            st.extracted |= {int(i) for i in data.get("parts") or [] if str(i).isdigit()}
            st.extracted_full = st.extracted_full or bool(data.get("full"))
            if st.n_parts is None and isinstance(data.get("n_parts"), int):
                st.n_parts = data["n_parts"]
            if key in states or not st.complete:
                states[key] = st
    return states


def _safe_extract(zip_path: Path, week: str | tuple[str, ...], target: Path) -> None:
    prefixes = (week,) if isinstance(week, str) else tuple(week)
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = PurePosixPath(info.filename.replace("\\", "/"))
            parts = rel.parts
            if parts and parts[0] in prefixes:
                parts = parts[1:]
            if not parts or any(p in ("..", "") for p in parts) or PurePosixPath(*parts).is_absolute():
                raise ValueError(f"unsafe zip member: {info.filename}")
            dest = (target / Path(*parts)).resolve()
            if root != dest and root not in dest.parents:
                raise ValueError(f"zip member escapes target: {info.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def extract_week(state: InboxState, workspace_dir: Path) -> Path:
    """Extract the zips the state holds into weeks/<week>/, move them to done/, and note what has been seen."""
    target = Path(workspace_dir) / "weeks" / state.week
    for zp in state.zips():
        _safe_extract(zp, state.prefixes, target)
    if state.zips():
        done = state.zips()[0].parent / "done"
        done.mkdir(exist_ok=True)
        for zp in state.zips():
            shutil.move(str(zp), str(done / zp.name))
    marker = _marker(workspace_dir, state.week, state.round)
    old = _read_marker(marker) if marker.is_file() else {}
    seen = sorted({int(i) for i in old.get("parts") or [] if str(i).isdigit()} | set(state.parts) | set(state.extracted))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"n_parts": state.n_parts if state.n_parts is not None else old.get("n_parts"), "parts": seen,
                                  "full": bool(old.get("full")) or state.full is not None or state.extracted_full,
                                  "light": bool(old.get("light")) or state.light is not None}, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def process_once(inbox_dir: Path, workspace_dir: Path) -> list[str]:
    """Extract whatever zips the inbox holds, week by week, complete or not. Returns the weeks touched (sorted)."""
    extracted: list[str] = []
    for _key, state in sorted(scan(inbox_dir, workspace_dir).items()):
        if state.zips():
            extract_week(state, workspace_dir)
            if state.week not in extracted:
                extracted.append(state.week)
    return extracted
