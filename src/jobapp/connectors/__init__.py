"""Connectors: get told about job changes (e.g. to sync notes elsewhere).

Called after DB writes. Exceptions are caught and logged, never fail a poll.
Errors are kept in $JOBAPP_HOME/logs/connector_errors.json and shown by `doctor`.
"""
from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from .. import paths
from ..db import now
from ..log import get

log = get("connectors")


@runtime_checkable
class Connector(Protocol):
    name: str

    def on_job_added(self, job: dict) -> None: ...
    def on_job_updated(self, job: dict, changes: dict) -> None: ...
    def pull(self) -> list[dict]: ...


class NullConnector:
    name = "null"

    def on_job_added(self, job: dict) -> None:
        pass

    def on_job_updated(self, job: dict, changes: dict) -> None:
        pass

    def pull(self) -> list[dict]:
        return []


def _errors_file():
    return paths.logs_dir() / "connector_errors.json"


def _record_error(name: str, what: str, exc: BaseException) -> None:
    log.warning("connector %s %s failed: %r", name, what, exc)
    f = _errors_file()
    try:
        data = json.loads(f.read_text()) if f.exists() else {}
    except ValueError:
        data = {}
    data[name] = {"at": now(), "event": what, "error": f"{exc.__class__.__name__}: {exc}"}
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def _clear_error(name: str) -> None:
    f = _errors_file()
    if not f.exists():
        return
    try:
        data = json.loads(f.read_text())
        if data.pop(name, None) is not None:
            f.write_text(json.dumps(data, indent=2))
    except (OSError, ValueError):
        pass


def load(cfg) -> list[Connector]:
    from .jsonl import JsonlConnector
    out: list[Connector] = []
    if cfg.connectors.jsonl.enabled:
        out.append(JsonlConnector(paths.output_dir() / "events.jsonl"))
    # obsidian: interface reserved, not built in v0.1
    return out


def _dispatch(cfg, method: str, *args) -> None:
    try:
        conns = load(cfg)
    except Exception as e:  # noqa: BLE001
        _record_error("loader", method, e)
        return
    for c in conns:
        try:
            getattr(c, method)(*args)
            _clear_error(c.name)
        except Exception as e:  # noqa: BLE001
            _record_error(c.name, method, e)


def notify_added(cfg, job: dict) -> None:
    _dispatch(cfg, "on_job_added", job)


def notify_updated(cfg, job: dict, changes: dict) -> None:
    _dispatch(cfg, "on_job_updated", job, changes)


def doctor_checks(cfg) -> list:
    from ..doctor import FAIL, OK, WARN, Check
    out = []
    try:
        conns = load(cfg)
    except Exception as e:  # noqa: BLE001
        return [Check("Connectors", FAIL, str(e), "Check the 'connectors' part of config.yaml.")]
    f = _errors_file()
    errs = {}
    if f.exists():
        try:
            errs = json.loads(f.read_text())
        except ValueError:
            pass
    if cfg.connectors.obsidian.enabled:
        out.append(Check("Connector: obsidian", WARN, "not available in this version",
                         "Set connectors.obsidian.enabled to false for now."))
    for c in conns:
        e = errs.get(c.name)
        if e:
            out.append(Check(f"Connector: {c.name}", WARN, f"{e['at'][:16]} {e['error']}",
                             "Jobs are still saved; only the connector missed an update."))
        else:
            out.append(Check(f"Connector: {c.name}", OK, "working"))
    return out
