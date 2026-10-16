"""Find external programs (TeX, pandoc, pdftotext) even when PATH is minimal (launchd/cron)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

EXTRA_DIRS = [
    "~/.local/bin", "~/bin", "~/.cargo/bin",
    "/opt/homebrew/bin", "/usr/local/bin", "/Library/TeX/texbin", "/usr/bin",
]


def which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_DIRS:
        p = Path(os.path.expanduser(d)) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None
