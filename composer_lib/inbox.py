"""Inbox: collect the mailed zips of a week, extract them once all parts are present, move them to done/.

File names come from the server's mail.py: <week>.zip (full), <week>-light.zip, <week>-part<i>of<n>.zip.
Every member path starts with "<week>/", so merging is plain overwrite into one folder.
"""
from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

NAME_RE = re.compile(r"^(?P<week>\d{4}-W\d{2})(?:-(?P<kind>light|part(?P<i>\d+)of(?P<n>\d+)))?\.zip$")


@dataclass
class InboxState:
    week: str
    full: Path | None = None
    light: Path | None = None
    parts: dict[int, Path] = field(default_factory=dict)
    n_parts: int | None = None

    @property
    def missing_parts(self) -> list[int]:
        if self.n_parts is None:
            return []
        return [i for i in range(1, self.n_parts + 1) if i not in self.parts]

    @property
    def complete(self) -> bool:
        if self.full is not None:
            return True
        return self.n_parts is not None and not self.missing_parts

    def zips(self) -> list[Path]:
        """Extraction order: light first (text), then full, then parts in order; later files overwrite earlier."""
        out = [p for p in (self.light, self.full) if p]
        out += [self.parts[i] for i in sorted(self.parts)]
        return out

    def summary(self) -> dict:
        return {"week": self.week, "complete": self.complete, "has_full": self.full is not None, "has_light": self.light is not None,
                "parts": sorted(self.parts), "n_parts": self.n_parts, "missing_parts": self.missing_parts}


def scan(inbox_dir: Path) -> dict[str, InboxState]:
    inbox_dir = Path(inbox_dir)
    states: dict[str, InboxState] = {}
    if not inbox_dir.exists():
        return states
    for p in sorted(inbox_dir.glob("*.zip")):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        st = states.setdefault(m["week"], InboxState(week=m["week"]))
        kind = m["kind"]
        if kind is None:
            st.full = p
        elif kind == "light":
            st.light = p
        else:
            st.parts[int(m["i"])] = p
            st.n_parts = int(m["n"])
    return states


def _safe_extract(zip_path: Path, week: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = PurePosixPath(info.filename.replace("\\", "/"))
            parts = rel.parts
            if parts and parts[0] == week:
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
    target = Path(workspace_dir) / "weeks" / state.week
    for zp in state.zips():
        _safe_extract(zp, state.week, target)
    done = state.zips()[0].parent / "done"
    done.mkdir(exist_ok=True)
    for zp in state.zips():
        shutil.move(str(zp), str(done / zp.name))
    return target


def process_once(inbox_dir: Path, workspace_dir: Path) -> list[str]:
    """Extract every complete week found in the inbox. Returns the weeks extracted (sorted)."""
    extracted = []
    for week, state in sorted(scan(inbox_dir).items()):
        if state.complete:
            extract_week(state, workspace_dir)
            extracted.append(week)
    return extracted
