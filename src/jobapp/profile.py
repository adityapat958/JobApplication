"""Create the personal data folder from the bundled example profile."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import db, paths


def init(force: bool = False) -> tuple[Path, list[str]]:
    home = paths.home()
    created: list[str] = []
    src = paths.examples_profile()
    home.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.rglob("*")):
        if f.is_dir():
            continue
        rel = f.relative_to(src)
        dst = home / rel
        if dst.exists() and not force:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        created.append(str(rel))
    for d in ("output", "logs", "import"):
        (home / d).mkdir(exist_ok=True)
    existed = paths.db_path().exists()
    conn = db.connect()
    conn.close()
    if not existed:
        created.append("jobs.db")
    return home, created
