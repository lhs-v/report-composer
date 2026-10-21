"""Configuration for the composer. One JSON file; the Confluence PAT never leaves this module unmasked."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PORT = 8790


@dataclass
class ConfluenceConfig:
    base_url: str = ""
    pat: str = ""
    default_space: str = ""
    default_parent_id: str = ""
    verify_ssl: bool = True
    ca_bundle: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.pat)


@dataclass
class Config:
    inbox_dir: Path = field(default_factory=lambda: Path.home() / "Downloads" / "report-inbox")
    workspace_dir: Path = field(default_factory=lambda: Path.home() / "report-composer")
    port: int = DEFAULT_PORT
    confluence: ConfluenceConfig = field(default_factory=ConfluenceConfig)
    path: Path | None = None

    def public(self) -> dict:
        """What the UI may see: paths and flags, with the token masked."""
        d = asdict(self)
        d["inbox_dir"], d["workspace_dir"], d["path"] = str(self.inbox_dir), str(self.workspace_dir), (str(self.path) if self.path else None)
        d["confluence"]["pat"] = "***" if self.confluence.pat else ""
        d["confluence"]["configured"] = self.confluence.configured
        return d


def load_config(path: Path | None) -> Config:
    cfg = Config(path=Path(path) if path else None)
    if path and Path(path).exists():
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("inbox_dir"):
            cfg.inbox_dir = Path(raw["inbox_dir"]).expanduser()
        if raw.get("workspace_dir"):
            cfg.workspace_dir = Path(raw["workspace_dir"]).expanduser()
        if raw.get("port"):
            cfg.port = int(raw["port"])
        c = raw.get("confluence") or {}
        cfg.confluence = ConfluenceConfig(
            base_url=str(c.get("base_url") or "").rstrip("/"),
            pat=str(c.get("pat") or ""),
            default_space=str(c.get("default_space") or ""),
            default_parent_id=str(c.get("default_parent_id") or ""),
            verify_ssl=bool(c.get("verify_ssl", True)),
            ca_bundle=str(c.get("ca_bundle") or ""),
        )
    return cfg
