"""File logging under $JOBAPP_HOME/logs. The console stays plain English."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import paths

_configured = False


def setup() -> logging.Logger:
    global _configured
    log = logging.getLogger("jobapp")
    if _configured:
        return log
    log.setLevel(logging.INFO)
    try:
        d = paths.logs_dir()
        d.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(d / "jobapp.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())
    _configured = True
    return log


def get(name: str = "jobapp") -> logging.Logger:
    setup()
    return logging.getLogger(name if name.startswith("jobapp") else f"jobapp.{name}")
