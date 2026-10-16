"""Where things live. Everything personal is under JOBAPP_HOME (never in git)."""
from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_DIR = PKG_DIR.parent.parent


def home() -> Path:
    env = os.environ.get("JOBAPP_HOME")
    return Path(env).expanduser() if env else Path.home() / "JobApplication-data"


def _bundled(*parts: str) -> Path:
    """Locate a bundled resource: repo checkout first, then the installed wheel."""
    repo = REPO_DIR.joinpath(*parts)
    if repo.exists():
        return repo
    return PKG_DIR.joinpath("_" + parts[0], *parts[1:])


def examples_profile() -> Path:
    return _bundled("examples", "profile")


def prompts_dir() -> Path:
    return _bundled("prompts")


def config_path() -> Path:
    return home() / "config.yaml"


def db_path() -> Path:
    return home() / "jobs.db"


def output_dir() -> Path:
    return home() / "output"


def logs_dir() -> Path:
    return home() / "logs"


def import_dir() -> Path:
    return home() / "import"
