"""Findings of an XWaermeplan export, all levels in one report."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

#: structure: fields, code lists, units, references (xplan-tools)
#: schema: the GML against the XSD (with schema_dir)
#: consistency: the export against the F|Heat result it came from
#: conformity: the conformity conditions of the schema documentation (mapping.CONFORMITY)
#: A finding on any level means no file is written.
LEVELS = ("structure", "schema", "consistency", "conformity")


@dataclass(frozen=True)
class Issue:
    level: str
    feature: Optional[str]   # "<feature type> <key>", or None for the whole export
    message: str


@dataclass
class ExportReport:
    files: dict[str, Path] = field(default_factory=dict)   # format ("gml", "jsonfg") -> written file; {} with findings
    counts: dict[str, int] = field(default_factory=dict)   # feature type -> number of features
    issues: list[Issue] = field(default_factory=list)
    schema_checked: bool = False                            # False: no XSD given, level "schema" skipped
    notes: list[str] = field(default_factory=list)          # what the user should know; not findings, ok stays

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "files": {fmt: str(path) for fmt, path in self.files.items()},
            "counts": dict(self.counts),
            "schema_checked": self.schema_checked,
            "issues": [{"level": i.level, "feature": i.feature, "message": i.message} for i in self.issues],
            "notes": list(self.notes),
        }
