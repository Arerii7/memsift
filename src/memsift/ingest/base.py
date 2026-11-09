from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class IngestStats:
    files: int = 0
    records: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "files": self.files,
            "records": self.records,
            "skipped": self.skipped,
            "errors": list(self.errors),
            "paths": [str(path) for path in self.paths],
        }
