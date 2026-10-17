"""SQLite storage. Migrations are numbered SQL files applied via PRAGMA user_version."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .. import paths
from ..filters import title_score
from ..models import STATUSES, JobPosting
from . import dedupe as dd

MIGRATIONS = Path(__file__).parent / "migrations"
DONE_STATUSES = {"applied", "interview", "rejected", "offer"}
# Listing fields refreshed on every re-poll. status/done/notes/hand-saved JD are never touched.
REFRESH_FIELDS = ("url", "apply_url", "company", "title", "location", "job_type", "posted_at", "raw")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def migrations() -> list[tuple[int, Path]]:
    out = []
    for f in sorted(MIGRATIONS.glob("*.sql")):
        m = re.match(r"(\d+)_", f.name)
        if m:
            out.append((int(m[1]), f))
    return out


def latest_version() -> int:
    return max((v for v, _ in migrations()), default=0)


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _post_migrate(conn: sqlite3.Connection, v: int) -> None:
    """Python data steps that run inside a migration's transaction."""
    if v == 2:
        from .dedupe import dedupe_all
        dedupe_all(conn)


def migrate(conn: sqlite3.Connection) -> int:
    cur = schema_version(conn)
    for v, f in migrations():
        if v > cur:
            conn.executescript(f"BEGIN;\n{f.read_text()}\n")
            try:
                _post_migrate(conn, v)
                conn.execute(f"PRAGMA user_version = {v}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            cur = v
    return cur


def connect(path: Path | str | None = None, *, do_migrate: bool = True) -> sqlite3.Connection:
    path = Path(path) if path else paths.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    if do_migrate:
        migrate(conn)
    return conn


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.replace(microsecond=0).isoformat()
    return str(v)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("raw", "matched", "missing"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                pass
        elif k != "raw":
            d[k] = []
    return d


def upsert_job(conn: sqlite3.Connection, job: JobPosting, ts: str | None = None) -> tuple[str, bool]:
    """Insert a posting or refresh its listing fields. Returns (id, is_new)."""
    ts = ts or now()
    vals = {
        "url": job.url, "apply_url": job.apply_url or job.url, "company": job.company,
        "title": job.title, "location": job.location, "job_type": job.job_type,
        "posted_at": _iso(job.posted_at), "raw": json.dumps(job.raw, default=str, ensure_ascii=False),
    }
    existing = conn.execute("SELECT id, jd_saved_at, description FROM jobs WHERE source=? AND source_id=?",
                            (job.source, job.source_id)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO jobs (id, source, source_id, first_seen_at, last_seen_at, status_updated_at, description, "
            "language, " + ", ".join(vals) + ") VALUES (?,?,?,?,?,?,?,?," + ",".join("?" * len(vals)) + ")",
            (job.id, job.source, job.source_id, ts, ts, ts, job.description, job.language, *vals.values()),
        )
        dd.set_key(conn, job.id)
        dd.relink_job(conn, job.id)
        return job.id, True
    sets = {k: v for k, v in vals.items() if v not in (None, "") or k == "raw"}
    sets["last_seen_at"] = ts
    if job.description and not existing["jd_saved_at"]:
        sets["description"] = job.description
    if job.language:
        sets["language"] = job.language
    conn.execute("UPDATE jobs SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?",
                 (*sets.values(), existing["id"]))
    dd.set_key(conn, existing["id"])
    dd.relink_job(conn, existing["id"])
    return existing["id"], False


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None and job_id:
        rows = conn.execute("SELECT * FROM jobs WHERE id LIKE ?", (job_id + "%",)).fetchall()
        row = rows[0] if len(rows) == 1 else None
    d = row_to_dict(row)
    if d:
        d["also_on"] = also_on(conn, [d["id"]]).get(d["id"], [])
    return d


def also_on(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[dict]]:
    """primary id -> [{source, url, id}] of its hidden cross-source duplicates."""
    out: dict[str, list[dict]] = {}
    if not ids:
        return out
    q = "SELECT id, source, url, apply_url, duplicate_of FROM jobs WHERE duplicate_of IS NOT NULL"
    if len(ids) <= 500:
        q += " AND duplicate_of IN (" + ",".join("?" * len(ids)) + ")"
        args = ids
    else:
        args = []
    want = set(ids)
    for r in conn.execute(q + " ORDER BY source", args):
        if r["duplicate_of"] in want:
            out.setdefault(r["duplicate_of"], []).append({"source": r["source"], "url": r["url"] or r["apply_url"],
                                                          "id": r["id"]})
    return out


def list_jobs(conn: sqlite3.Connection, *, status: str | None = None, min_match: float | None = None,
              include_hidden: bool = False, only_hidden: bool = False, query: str | None = None,
              source: str | None = None, limit: int | None = None, order: str = "newest",
              title_include: list[str] | None = None, include_duplicates: bool = False) -> list[dict]:
    """title_include (filters.title_include) adds a title_score to each row; order="match" sorts by
    match_pct desc, then title_score desc, then posted desc."""
    where, args = [], []
    if not include_duplicates:
        where.append("j.duplicate_of IS NULL")  # cross-source copies show as "also on" on the primary
    if status:
        where.append("j.status=?"); args.append(status)
    if min_match is not None:
        where.append("COALESCE(j.match_pct,0) >= ?"); args.append(min_match)
    if only_hidden:
        where.append("j.hidden=1")
    elif not include_hidden:
        where.append("j.hidden=0")
    if source:
        where.append("j.source=?"); args.append(source)
    if query:
        where.append("j.rowid IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)")
        args.append(_fts_query(query))
    orders = {
        "newest": "COALESCE(j.posted_at, j.first_seen_at) DESC",
        "match": "COALESCE(j.match_pct,-1) DESC, COALESCE(j.posted_at, j.first_seen_at) DESC",
        "company": "lower(j.company) ASC",
    }
    sql = "SELECT j.* FROM jobs j"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + orders.get(order, orders["newest"])
    if limit and order != "match":
        sql += f" LIMIT {int(limit)}"
    rows = [row_to_dict(r) for r in conn.execute(sql, args)]
    extra = also_on(conn, [r["id"] for r in rows])
    for r in rows:
        r["title_score"] = title_score(r.get("title"), title_include)
        r["also_on"] = extra.get(r["id"], [])
    if order == "match":
        rows.sort(key=lambda r: r.get("posted_at") or r.get("first_seen_at") or "", reverse=True)
        rows.sort(key=lambda r: (r["match_pct"] if r.get("match_pct") is not None else -1, r["title_score"]),
                  reverse=True)
        rows = rows[:int(limit)] if limit else rows
    return rows


def _fts_query(q: str) -> str:
    terms = re.findall(r"\w+", q, flags=re.UNICODE)
    return " ".join(f'"{t}"*' for t in terms) or '""'


def set_status(conn: sqlite3.Connection, job_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
    done = 1 if status in DONE_STATUSES else 0
    ts = now()
    conn.execute("UPDATE jobs SET status=?, done=?, done_at=CASE WHEN ?=1 THEN COALESCE(done_at, ?) ELSE NULL END, "
                 "status_updated_at=CASE WHEN status=? THEN status_updated_at ELSE ? END WHERE id=?",
                 (status, done, done, ts, status, ts, job_id))
    dd.relink_job(conn, job_id)
    return get_job(conn, job_id)


def mark(conn: sqlite3.Connection, job_id: str, status: str) -> tuple[dict, str]:
    """The user's "mark" action: set the status and un-hide a job they track. Returns (job, old status).
    Callers then tell the connectors (connectors.notify_updated)."""
    j = get_job(conn, job_id)
    if not j:
        raise KeyError(job_id)
    j2 = set_status(conn, j["id"], status)
    if status != "new" and j2["hidden"]:
        set_hidden(conn, j["id"], False)  # a job you're tracking is never hidden
        j2 = get_job(conn, j["id"])
    return j2, j["status"]


def set_done(conn: sqlite3.Connection, job_id: str, done: bool) -> dict:
    status = "applied" if done else "new"
    return set_status(conn, job_id, status)


def set_notes(conn: sqlite3.Connection, job_id: str, notes: str) -> None:
    conn.execute("UPDATE jobs SET notes=? WHERE id=?", (notes, job_id))
    dd.relink_job(conn, job_id)


def set_description(conn: sqlite3.Connection, job_id: str, text: str | None, *, manual: bool) -> None:
    """manual=True marks the JD as hand-saved: re-polls will never overwrite it."""
    if manual:
        conn.execute("UPDATE jobs SET description=?, jd_saved_at=? WHERE id=?", (text, now(), job_id))
    else:
        conn.execute("UPDATE jobs SET description=? WHERE id=? AND jd_saved_at IS NULL", (text, job_id))
    dd.relink_job(conn, job_id)


def set_match(conn: sqlite3.Connection, job_id: str, pct: float, matched: list, missing: list) -> None:
    conn.execute("UPDATE jobs SET match_pct=?, matched=?, missing=? WHERE id=?",
                 (pct, json.dumps(matched, ensure_ascii=False), json.dumps(missing, ensure_ascii=False), job_id))


def set_hidden(conn: sqlite3.Connection, job_id: str, hidden: bool, reason: str = "") -> None:
    conn.execute("UPDATE jobs SET hidden=?, hidden_reason=? WHERE id=?",
                 (1 if hidden else 0, reason if hidden else None, job_id))
    dd.relink_job(conn, job_id)


def start_run(conn: sqlite3.Connection, source: str) -> int:
    return conn.execute("INSERT INTO runs (started_at, source) VALUES (?,?)", (now(), source)).lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, fetched: int, new: int, errors: Iterable[str]) -> None:
    errs = list(errors)
    conn.execute("UPDATE runs SET finished_at=?, fetched=?, new=?, errors=? WHERE id=?",
                 (now(), fetched, new, json.dumps(errs) if errs else None, run_id))


def last_runs(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


def add_build(conn: sqlite3.Connection, job_id: str, pdf_path: str, keywords: list) -> None:
    conn.execute("INSERT INTO builds (job_id, pdf_path, created_at, keywords) VALUES (?,?,?,?)",
                 (job_id, pdf_path, now(), json.dumps(keywords, ensure_ascii=False)))


def last_build(conn: sqlite3.Connection, job_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM builds WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    return dict(r) if r else None


def counts(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    dups = conn.execute("SELECT COUNT(*) FROM jobs WHERE duplicate_of IS NOT NULL").fetchone()[0]
    hidden = conn.execute("SELECT COUNT(*) FROM jobs WHERE hidden=1 AND duplicate_of IS NULL").fetchone()[0]
    by_status = {r[0]: r[1] for r in conn.execute(
        "SELECT status, COUNT(*) FROM jobs WHERE duplicate_of IS NULL GROUP BY status")}
    return {"total": total, "hidden": hidden, "duplicates": dups, "visible": total - hidden - dups,
            "by_status": by_status}
