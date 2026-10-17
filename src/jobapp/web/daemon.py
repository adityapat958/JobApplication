"""Run the dashboard in the background so it survives the command that started it.

Claude Code (and Claude Desktop) run each command with a time limit and stop it afterwards, so a
foreground `jobapp serve` dies or blocks the agent. `jobapp serve --background` starts a detached
process, records its PID/port in logs/dashboard.json, and returns immediately.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .. import paths


def _state_file():
    return paths.logs_dir() / "dashboard.json"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def free_port(preferred: int = 8765, tries: int = 20) -> int:
    """`preferred` if nothing listens there, else the next free port."""
    for p in range(preferred, preferred + tries):
        if _port_free(p):
            return p
    raise RuntimeError(f"No free port between {preferred} and {preferred + tries - 1}.")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _ours(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return json.loads(r.read() or b"{}").get("app") == "jobapp"
    except Exception:
        return False


def _read():
    try:
        return json.loads(_state_file().read_text())
    except Exception:
        return None


def status() -> str:
    st = _read()
    if st and _alive(st["pid"]) and _ours(st["port"]):
        return f"Dashboard is running at http://127.0.0.1:{st['port']}"
    return "Dashboard is not running. Start it with: uv run jobapp serve --background"


def start(port: int = 8765, open_browser: bool = True, wait: float = 20.0) -> str:
    st = _read()
    if st and _alive(st["pid"]) and _ours(st["port"]):
        url = f"http://127.0.0.1:{st['port']}"
        if open_browser:
            webbrowser.open(url)
        return f"Dashboard already running at {url}"
    port = free_port(port)
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    log = open(paths.logs_dir() / "dashboard.log", "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "jobapp.cli_entry", "serve", "--port", str(port), "--no-open"],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, env=os.environ.copy(), close_fds=True,
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None:
            return ("The dashboard could not start. Details are in "
                    f"{paths.logs_dir() / 'dashboard.log'} (run: uv run jobapp doctor).")
        if _ours(port):
            _state_file().write_text(json.dumps({"pid": proc.pid, "port": port}))
            url = f"http://127.0.0.1:{port}"
            if open_browser:
                webbrowser.open(url)
            return f"Dashboard running at {url} (it keeps running; stop it with: uv run jobapp serve --stop)"
        time.sleep(0.3)
    proc.terminate()
    return f"The dashboard did not answer within {int(wait)} s. Details: {paths.logs_dir() / 'dashboard.log'}"


def stop() -> str:
    st = _read()
    if not st or not _alive(st["pid"]):
        _state_file().unlink(missing_ok=True)
        return "Dashboard was not running."
    os.killpg(os.getpgid(st["pid"]), signal.SIGTERM) if hasattr(os, "killpg") else os.kill(st["pid"], signal.SIGTERM)
    _state_file().unlink(missing_ok=True)
    return "Dashboard stopped."
