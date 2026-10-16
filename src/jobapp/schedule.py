"""Automatic searches: launchd on macOS (installed for you), cron on Linux (line printed, never edited)."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import paths
from .platform import is_mac

LABEL = "com.jobapplication.poll"
CRON_TAG = "# jobapplication-poll"
EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/Library/TeX/texbin", "/usr/bin", "/bin",
              str(Path.home() / ".local" / "bin"), str(Path.home() / ".cargo" / "bin")]


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def program_args() -> list[str]:
    return [sys.executable, "-m", "jobapp.cli_entry", "poll"]


def _times(cfg) -> list[tuple[int, int]]:
    out = []
    for t in cfg.schedule.times:
        h, m = str(t).split(":")
        out.append((int(h), int(m)))
    return sorted(set(out))


def plist_dict(cfg) -> dict:
    logs = paths.logs_dir()
    return {
        "Label": LABEL,
        "ProgramArguments": program_args(),
        "StartCalendarInterval": [{"Hour": h, "Minute": m} for h, m in _times(cfg)],
        "EnvironmentVariables": {"JOBAPP_HOME": str(paths.home()),
                                 "PATH": ":".join(dict.fromkeys(EXTRA_PATH + os.environ.get("PATH", "").split(":")))},
        "WorkingDirectory": str(paths.home()),
        "StandardOutPath": str(logs / "schedule.log"),
        "StandardErrorPath": str(logs / "schedule.log"),
        "RunAtLoad": False,
        "ProcessType": "Background",
    }


def plist_bytes(cfg) -> bytes:
    return plistlib.dumps(plist_dict(cfg), sort_keys=False)


def crontab_lines(cfg) -> list[str]:
    cmd = " ".join(_q(a) for a in program_args())
    log = _q(str(paths.logs_dir() / "schedule.log"))
    env = f"JOBAPP_HOME={_q(str(paths.home()))}"
    return [f"{m} {h} * * * {env} {cmd} >> {log} 2>&1 {CRON_TAG}" for h, m in _times(cfg)]


def _q(s: str) -> str:
    return s if all(c.isalnum() or c in "/._-:=" for c in s) else "'" + s.replace("'", "'\\''") + "'"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(cfg) -> str:
    times = ", ".join(f"{h:02d}:{m:02d}" for h, m in _times(cfg))
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    if is_mac():
        p = plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            _launchctl("unload", str(p))
        p.write_bytes(plist_bytes(cfg))
        r = _launchctl("load", "-w", str(p))
        if r.returncode != 0:
            return f"Saved the schedule but macOS didn't start it: {r.stderr.strip() or r.stdout.strip()}"
        return (f"Automatic job searches are on: every day at {times}.\n"
                f"(Your Mac must be awake. Log: {paths.logs_dir() / 'schedule.log'})")
    lines = "\n".join(crontab_lines(cfg))
    return ("On Linux, add this to your crontab (run 'crontab -e' and paste it at the end):\n\n"
            f"{lines}\n\nJobApplication does not edit your crontab itself.")


def remove() -> str:
    if is_mac():
        p = plist_path()
        if not p.exists():
            return "Automatic searches were not on."
        _launchctl("unload", str(p))
        p.unlink()
        return "Automatic searches are off."
    return f"On Linux, run 'crontab -e' and delete the line(s) ending in '{CRON_TAG}'."


def status(cfg) -> str:
    if is_mac():
        p = plist_path()
        if not p.exists():
            return "Automatic searches are off. Turn on with: jobapp schedule install"
        loaded = LABEL in _launchctl("list").stdout
        try:
            d = plistlib.loads(p.read_bytes())
            when = ", ".join(f"{x['Hour']:02d}:{x['Minute']:02d}" for x in d.get("StartCalendarInterval", []))
        except Exception:  # noqa: BLE001
            when = "?"
        state = "on" if loaded else "installed but not loaded (run 'jobapp schedule install' again)"
        return f"Automatic searches are {state}: every day at {when}."
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except OSError:
        cur = ""
    n = sum(CRON_TAG in l for l in cur.splitlines())
    if n:
        return f"Automatic searches are on ({n} crontab line(s))."
    return "Automatic searches are off. 'jobapp schedule install' shows the crontab line to add."
