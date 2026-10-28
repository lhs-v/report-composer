"""Configuration for the composer. One JSON file; the Confluence PAT never leaves this module unmasked."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .llm import PROVIDERS, ProviderSpec

DEFAULT_PORT = 8790


@dataclass
class ConfluenceConfig:
    base_url: str = ""
    pat: str = ""
    default_space: str = ""
    default_parent_id: str = ""
    verify_ssl: bool = True
    ca_bundle: str = ""
    email: str = ""          # Confluence Cloud: API token + account email (Basic auth). Empty = Data Center PAT (Bearer).

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.pat)

    @property
    def is_cloud(self) -> bool:
        return bool(self.email)


@dataclass
class GeminiConfig:
    """The Gemini CLI that polishes a draft: `command` is the executable (a path or a command line, split like a
    shell would), `model` the default model the dialog offers."""
    command: str = "gemini"
    model: str = "gemini-3.8-flash"


@dataclass
class LlmConfig:
    """Which command-line model tool writes and polishes text. Empty `provider` = not chosen yet. `command` and
    `model` fall back to the vocabulary table; `fallback` is tried once when the main provider fails."""
    provider: str = ""
    command: str = ""
    model: str = ""
    fallback: ProviderSpec | None = None


@dataclass
class Config:
    inbox_dir: Path = field(default_factory=lambda: Path.home() / "Downloads" / "report-inbox")
    workspace_dir: Path = field(default_factory=lambda: Path.home() / "report-composer")
    port: int = DEFAULT_PORT
    # result pages are served from this host name and the UI from 127.0.0.1: two origins, so a page's scripts
    # cannot call the composer's API (drafts, Confluence publishing)
    page_host: str = "localhost"
    confluence: ConfluenceConfig = field(default_factory=ConfluenceConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    path: Path | None = None

    def public(self) -> dict:
        """What the UI may see: paths and flags, with the token masked."""
        d = asdict(self)
        d["inbox_dir"], d["workspace_dir"], d["path"] = str(self.inbox_dir), str(self.workspace_dir), (str(self.path) if self.path else None)
        d["confluence"]["pat"] = "***" if self.confluence.pat else ""
        d["confluence"]["configured"] = self.confluence.configured
        d["llm"] = asdict(self.llm)                        # commands and model names only; no secrets here
        d["providers"] = {k: dict(v) for k, v in PROVIDERS.items()}
        return d


def page_host(value: str) -> str:
    """A host name for result pages that differs from the UI's 127.0.0.1: an IP address, a port or the UI host
    itself would put pages back in the UI's origin, so those fall back to localhost."""
    v = value.strip().lower()
    if not v or ":" in v or "[" in v or re.fullmatch(r"[\d.]+", v) or not re.fullmatch(r"[a-z0-9.-]+", v):
        print(f"page_host {value!r} is not a host name apart from 127.0.0.1; using localhost")
        return "localhost"
    return v


def _spec_from_raw(d: dict) -> ProviderSpec | None:
    if not isinstance(d, dict) or not d.get("provider"):
        return None
    return ProviderSpec(str(d["provider"]), str(d.get("command") or ""), str(d.get("model") or ""))


def _llm_from_raw(d: dict) -> LlmConfig:
    return LlmConfig(provider=str(d.get("provider") or ""), command=str(d.get("command") or ""), model=str(d.get("model") or ""),
                     fallback=_spec_from_raw(d.get("fallback")))


def save_llm(path: Path, llm: LlmConfig) -> None:
    """Rewrite only the `llm` key of the config file (every other key, the Confluence token included, stays as it is)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw["llm"] = asdict(llm)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


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
        if raw.get("page_host"):
            cfg.page_host = page_host(str(raw["page_host"]))
        g = raw.get("gemini") or {}
        cfg.gemini = GeminiConfig(command=str(g.get("command") or "gemini"), model=str(g.get("model") or GeminiConfig.model))
        if isinstance(raw.get("llm"), dict):
            cfg.llm = _llm_from_raw(raw["llm"])
        elif raw.get("gemini"):                            # a config from before the llm key: it meant Gemini
            cfg.llm = LlmConfig(provider="gemini", command=cfg.gemini.command, model=cfg.gemini.model)
        c = raw.get("confluence") or {}
        cfg.confluence = ConfluenceConfig(
            base_url=str(c.get("base_url") or "").rstrip("/"),
            pat=str(c.get("pat") or ""),
            default_space=str(c.get("default_space") or ""),
            default_parent_id=str(c.get("default_parent_id") or ""),
            verify_ssl=bool(c.get("verify_ssl", True)),
            ca_bundle=str(c.get("ca_bundle") or ""),
            email=str(c.get("email") or ""),
        )
    return cfg
