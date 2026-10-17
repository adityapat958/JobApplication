"""config.yaml models (pydantic v2) + friendly validation."""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import paths

JobType = Literal["fulltime", "internship", "parttime", "contract", "temporary"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileCfg(_M):
    name: str = "Alex Example"
    locale: Literal["en", "no"] = "en"

    @property
    def first(self) -> str:
        return (self.name.split() or ["Me"])[0]

    @property
    def last(self) -> str:
        parts = self.name.split()
        return parts[-1] if len(parts) > 1 else ""


class SimplifyCfg(_M):
    enabled: bool = False
    lists: list[str] = Field(default_factory=lambda: ["summer_internships", "new_grad"])
    urls: dict[str, str] = Field(default_factory=dict)  # optional overrides name -> raw README URL


class LinkedInSearch(_M):
    keywords: str
    location: str = ""


class LinkedInCfg(_M):
    enabled: bool = False
    searches: list[LinkedInSearch] = Field(default_factory=list)
    max_pages: int = Field(3, ge=1, le=40)
    fetch_descriptions: bool = True


class FinnSearch(_M):
    q: str
    location: str = ""


class FinnCfg(_M):
    enabled: bool = False
    searches: list[FinnSearch] = Field(default_factory=list)
    max_pages: int = Field(2, ge=1, le=20)
    fetch_descriptions: bool = True


class BiPortalCfg(_M):
    enabled: bool = False


class SourcesCfg(_M):
    simplify: SimplifyCfg = Field(default_factory=SimplifyCfg)
    linkedin: LinkedInCfg = Field(default_factory=LinkedInCfg)
    finn: FinnCfg = Field(default_factory=FinnCfg)
    bi_portal: BiPortalCfg = Field(default_factory=BiPortalCfg)


class FiltersCfg(_M):
    title_include: list[str] = Field(default_factory=list)
    title_exclude: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    job_types: list[JobType] = Field(default_factory=list)
    max_age_days: int | None = Field(None, ge=0)
    companies_include: list[str] = Field(default_factory=list)
    companies_exclude: list[str] = Field(default_factory=list)
    languages: list[Literal["en", "no"]] = Field(default_factory=list)


class ResumeCfg(_M):
    tex: str = "resume/resume.tex"
    keywords: str = "resume/keywords.yaml"
    output_name: str = "{first}_{last}_{company}_{role}"

    @field_validator("output_name")
    @classmethod
    def _placeholders(cls, v: str) -> str:
        bad = set(re.findall(r"{(\w+)}", v)) - {"first", "last", "company", "role", "date"}
        if bad:
            raise ValueError(f"unknown placeholder(s) {sorted(bad)}; allowed: first, last, company, role, date")
        return v


class ScheduleCfg(_M):
    times: list[str] = Field(default_factory=lambda: ["09:00", "18:00"])

    @field_validator("times")
    @classmethod
    def _hhmm(cls, v: list[str]) -> list[str]:
        for t in v:
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(t))
            if not m or int(m[1]) > 23 or int(m[2]) > 59:
                raise ValueError(f"'{t}' is not a time like 09:00")
        return v


class ToggleCfg(_M):
    enabled: bool = False


def _rel_folder(v: str, what: str) -> str:
    v = str(v).strip().strip("/")
    if not v:
        raise ValueError(f"{what} can't be empty")
    if Path(v).is_absolute() or ".." in Path(v).parts or v.startswith("~"):
        raise ValueError(f"'{v}' must be a folder name inside your vault (like 'Jobs'), not a full path")
    return v


class ObsidianSubfolders(_M):
    fulltime: str = "Full-Time"
    internship: str = "Internships"
    parttime: str = "Part-Time"

    @field_validator("fulltime", "internship", "parttime")
    @classmethod
    def _rel(cls, v: str) -> str:
        return _rel_folder(v, "subfolder")


class ObsidianCfg(_M):
    enabled: bool = False
    vault: str = "~/Documents/Obsidian Vault"
    folder: str = "Jobs"
    subfolders: ObsidianSubfolders = Field(default_factory=ObsidianSubfolders)
    only_visible: bool = True
    min_match: float = Field(0, ge=0, le=100)
    dashboard_note: bool = True
    two_way: bool = False
    git_push: bool = False

    @field_validator("folder")
    @classmethod
    def _rel(cls, v: str) -> str:
        return _rel_folder(v, "folder")

    @field_validator("vault")
    @classmethod
    def _vault(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("give the path of your Obsidian vault, e.g. '~/Documents/Obsidian Vault'")
        return str(v).strip()


class ConnectorsCfg(_M):
    obsidian: ObsidianCfg = Field(default_factory=ObsidianCfg)
    jsonl: ToggleCfg = Field(default_factory=ToggleCfg)


class Config(_M):
    profile: ProfileCfg = Field(default_factory=ProfileCfg)
    sources: SourcesCfg = Field(default_factory=SourcesCfg)
    filters: FiltersCfg = Field(default_factory=FiltersCfg)
    resume: ResumeCfg = Field(default_factory=ResumeCfg)
    schedule: ScheduleCfg = Field(default_factory=ScheduleCfg)
    connectors: ConnectorsCfg = Field(default_factory=ConnectorsCfg)

    def resolve(self, rel: str) -> Path:
        p = Path(rel).expanduser()
        return p if p.is_absolute() else paths.home() / p


class ConfigError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def _model_at(loc: tuple) -> type[BaseModel] | None:
    model: Any = Config
    for part in loc:
        if isinstance(part, int):
            continue
        f = getattr(model, "model_fields", {}).get(part)
        if f is None:
            return model
        ann = f.annotation
        inner = getattr(ann, "__args__", None)
        if inner and isinstance(inner[0], type) and issubclass(inner[0], BaseModel):
            ann = inner[0]
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            model = ann
        else:
            return None
    return model


def friendly_errors(err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = tuple(e["loc"])
        where = ".".join(str(x) for x in loc) or "(top level)"
        if e["type"] == "extra_forbidden":
            parent = _model_at(loc[:-1])
            key = str(loc[-1])
            known = list(getattr(parent, "model_fields", {}).keys()) if parent else []
            guess = difflib.get_close_matches(key, known, n=1, cutoff=0.5)
            hint = f" — did you mean '{guess[0]}'?" if guess else (
                f" — allowed here: {', '.join(known)}" if known else "")
            out.append(f"{where}: unknown setting '{key}'{hint}")
        elif e["type"] == "literal_error":
            allowed = e.get("ctx", {}).get("expected", "")
            val = e.get("input")
            opts = re.findall(r"'([^']+)'", str(allowed))
            guess = difflib.get_close_matches(str(val), opts, n=1, cutoff=0.5)
            hint = f" — did you mean '{guess[0]}'?" if guess else ""
            out.append(f"{where}: '{val}' is not allowed (choose from {allowed}){hint}")
        else:
            msg = e["msg"].removeprefix("Value error, ")
            out.append(f"{where}: {msg}")
    return out


def parse(data: dict | None) -> Config:
    try:
        return Config.model_validate(data or {})
    except ValidationError as e:
        raise ConfigError(friendly_errors(e)) from None


def runtime_problems(cfg: Config) -> list[str]:
    """Checks that need the filesystem (kept out of parsing so a missing vault never stops a poll)."""
    out = []
    ob = cfg.connectors.obsidian
    if ob.enabled:
        vault = cfg.resolve(ob.vault)
        if not vault.is_dir():
            out.append(f"connectors.obsidian.vault: folder not found: {vault} "
                       "(open Obsidian → 'Open folder as vault' shows where your vault is)")
    return out


def title_include() -> list[str]:
    """filters.title_include of the active profile, or [] if there is no valid config (ranking only)."""
    try:
        return list(load().filters.title_include)
    except Exception:  # noqa: BLE001
        return []


def load(path: Path | None = None) -> Config:
    path = path or paths.config_path()
    if not path.exists():
        raise ConfigError([f"No config found at {path}. Run 'jobapp init' first."])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise ConfigError([f"config.yaml is not valid YAML{where}: {getattr(e, 'problem', e)}. "
                           "Check indentation (use spaces, not tabs) and colons."]) from None
    if data is not None and not isinstance(data, dict):
        raise ConfigError(["config.yaml must be a set of 'key: value' settings at the top level."])
    return parse(data)


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or paths.config_path()
    data = cfg.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
