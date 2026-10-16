"""Keyword bank (keywords.yaml): what the user can honestly claim, plus JD-term aliases."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class BankError(ValueError):
    pass


def _flatten(section) -> list[str]:
    out: list[str] = []
    if section is None:
        return out
    if isinstance(section, list):
        items = section
    elif isinstance(section, dict):
        items = [x for v in section.values() for x in (v if isinstance(v, list) else [v] if v else [])]
    else:
        raise BankError("each section must be a list or groups of lists")
    for x in items:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


@dataclass
class Bank:
    core: list[str] = field(default_factory=list)
    tech: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)

    @property
    def all(self) -> list[str]:
        return self.core + [t for t in self.tech if t not in self.core]

    @classmethod
    def from_dict(cls, data: dict | None) -> "Bank":
        data = data or {}
        if not isinstance(data, dict):
            raise BankError("keywords.yaml must have core_competencies / technical_skills / aliases")
        unknown = set(data) - {"core_competencies", "technical_skills", "aliases"}
        if unknown:
            raise BankError(f"unknown section(s) in keywords.yaml: {', '.join(sorted(unknown))} "
                            "(allowed: core_competencies, technical_skills, aliases)")
        bank = cls(_flatten(data.get("core_competencies")), _flatten(data.get("technical_skills")),
                   {str(k): str(v) for k, v in (data.get("aliases") or {}).items()})
        if not bank.core and not bank.tech:
            raise BankError("keywords.yaml has no keywords yet")
        bad = [v for v in bank.aliases.values() if v not in bank.core and v not in bank.tech]
        if bad:
            raise BankError(f"alias target(s) not in your keyword list: {', '.join(bad)}")
        return bank

    @classmethod
    def load(cls, path: Path) -> "Bank":
        if not Path(path).exists():
            raise BankError(f"keyword list not found: {path}")
        try:
            return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except yaml.YAMLError as e:
            raise BankError(f"keywords.yaml is not valid YAML: {e}") from None
