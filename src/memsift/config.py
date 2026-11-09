from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def default_home() -> Path:
    raw = os.environ.get("MEMSIFT_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "memsift").resolve()


@dataclass(slots=True)
class Config:
    home: Path = field(default_factory=default_home)
    ttl_days: int = 0
    min_confidence: float = 0.0
    sources: list[dict[str, str]] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.home / "memsift.db"

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def add_source(self, kind: str, path: Path) -> bool:
        resolved = str(path.expanduser().resolve())
        item = {"kind": kind, "path": resolved}
        if item in self.sources:
            return False
        self.sources.append(item)
        return True

    def save(self) -> None:
        self.ensure_dirs()
        payload = {
            "ttl_days": self.ttl_days,
            "min_confidence": self.min_confidence,
            "sources": self.sources,
        }
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)

    @classmethod
    def load(cls, home: Path | None = None) -> Config:
        cfg = cls(home=home or default_home())
        if not cfg.config_path.exists():
            return cfg
        try:
            data: dict[str, Any] = json.loads(cfg.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cfg
        cfg.ttl_days = int(data.get("ttl_days", 0) or 0)
        cfg.min_confidence = float(data.get("min_confidence", 0.0) or 0.0)
        sources = data.get("sources", [])
        if isinstance(sources, list):
            cfg.sources = [
                {"kind": str(s.get("kind", "markdown")), "path": str(s.get("path", ""))}
                for s in sources
                if isinstance(s, dict) and s.get("path")
            ]
        return cfg


def project_scope(path: Path) -> str:
    return f"project:{path.expanduser().resolve()}"
