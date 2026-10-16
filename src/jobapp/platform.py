"""OS helpers: reveal a file in Finder / the file manager, open a URL."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def is_mac() -> bool:
    return sys.platform == "darwin"


def reveal_command(path: Path) -> list[str]:
    path = Path(path)
    if is_mac():
        return ["open", "-R", str(path)]
    if sys.platform.startswith("win"):
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path.parent if path.is_file() or path.suffix else path)]


def reveal(path: Path) -> bool:
    try:
        subprocess.Popen(reveal_command(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def folder_label() -> str:
    return "Show in Finder" if is_mac() else "Show in folder"
