"""Connectors: get told about job changes (e.g. to sync notes elsewhere).

Called after DB writes. Exceptions are caught and logged, never fail a poll.
Errors are kept in $JOBAPP_HOME/logs/connector_errors.json and shown by `doctor`.

Optional extras a connector may have (looked up with getattr):
- `two_way = True` + `pull()` returning [{id, status, applied, changed_at}] → `pull_all` at poll start
  applies note edits through the normal mark path when the note changed after the DB's last status change.
- `after_poll(conn)` → called once at the end of a poll (e.g. dashboards, git commit).
- `doctor()` → extra doctor checks.
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


_cache: dict = {}


def load(cfg) -> list[Connector]:
    """Connectors switched on in config. One set per config object (so a poll indexes the vault once)."""
    key = (id(cfg), str(paths.home()))
    if _cache.get("key") == key and _cache.get("cfg") is cfg:
        return _cache["conns"]
    from .jsonl import JsonlConnector
    out: list[Connector] = []
    if cfg.connectors.jsonl.enabled:
        out.append(JsonlConnector(paths.output_dir() / "events.jsonl"))
    if cfg.connectors.obsidian.enabled:
        from .obsidian import ObsidianConnector
        out.append(ObsidianConnector(cfg))
    _cache.update(key=key, cfg=cfg, conns=out)
    return out


def get(cfg, name: str):
    for c in load(cfg):
        if c.name == name:
            return c
    return None


# ── per-connector state (last sync, conflicts) ────────────
def _state_file():
    return paths.logs_dir() / "connector_state.json"


def _read_states() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {}


def load_state(name: str) -> dict:
    return dict(_read_states().get(name) or {})


def save_state(name: str, state: dict) -> None:
    data = _read_states()
    data[name] = state
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def record_conflict(name: str, job: dict, note_status: str, kept: str) -> None:
    log.info("connector %s conflict on %s: note=%s kept=%s", name, job.get("id"), note_status, kept)
    st = load_state(name)
    conf = st.get("conflicts") or []
    conf.append({"at": now(), "id": job.get("id"), "job": f"{job.get('company') or ''} — {job.get('title') or ''}",
                 "note": note_status, "kept": kept})
    st["conflicts"] = conf[-20:]
    save_state(name, st)


def recent_conflicts(name: str, days: int = 14) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [c for c in load_state(name).get("conflicts") or [] if c.get("at", "") >= cut]


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


def after_poll(cfg, conn) -> None:
    for c in _loaded(cfg, "after_poll"):
        try:
            c.after_poll(conn)
            _clear_error(c.name)
        except Exception as e:  # noqa: BLE001
            _record_error(c.name, "after_poll", e)


def _loaded(cfg, attr: str) -> list:
    try:
        return [c for c in load(cfg) if hasattr(c, attr)]
    except Exception as e:  # noqa: BLE001
        _record_error("loader", attr, e)
        return []


def apply_status(cfg, conn, job_id: str, status: str, *, origin: str) -> dict:
    """A status change coming from a connector, applied through the normal mark path."""
    from .. import db
    job, old = db.mark(conn, job_id, status)
    notify_updated(cfg, job, {"status": [old, status], "from": origin})
    return job


def pull_all(cfg, conn) -> int:
    """Two-way connectors: apply status edits made outside JobApplication (e.g. in an Obsidian note).
    A note edit wins only if it is newer than the DB's last status change; otherwise the DB wins, the note is
    rewritten and the conflict is shown by `doctor`. Returns how many jobs changed."""
    from .. import db
    from .obsidian import effective_status
    changed = 0
    for c in _loaded(cfg, "pull"):
        if not getattr(c, "two_way", False):
            continue
        try:
            for item in c.pull():
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (item.get("id"),)).fetchone()
                if row is None:
                    continue
                cur = row["status"]
                want = effective_status(item, cur)
                if not want or want == cur:
                    continue
                if (item.get("changed_at") or "") > (row["status_updated_at"] or ""):
                    apply_status(cfg, conn, row["id"], want, origin=c.name)
                    changed += 1
                else:
                    job = db.get_job(conn, row["id"])
                    record_conflict(c.name, job, want, cur)
                    c.on_job_updated(job, {"status": [want, cur], "conflict": True})
            _clear_error(c.name)
        except Exception as e:  # noqa: BLE001
            _record_error(c.name, "pull", e)
    return changed


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
    for c in conns:
        e = errs.get(c.name)
        if e:
            out.append(Check(f"Connector: {c.name}", WARN, f"{e['at'][:16]} {e['event']}: {e['error']}",
                             "Jobs are still saved; only the connector missed an update."))
        else:
            out.append(Check(f"Connector: {c.name}", OK, "working"))
        if hasattr(c, "doctor"):
            try:
                out += c.doctor()
            except Exception as ex:  # noqa: BLE001
                out.append(Check(f"Connector: {c.name}", WARN, f"check failed: {ex}"))
    return out
