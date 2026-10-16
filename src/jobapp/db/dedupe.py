"""Cross-source dedupe. Same normalised company + title from different sources within 45 days =
one job: the best row is the primary, the others point at it via duplicate_of (kept for their URL,
hidden from lists). Only duplicate_of is ever written — never status/done/notes."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from ..text import fold

WINDOW_DAYS = 45
# Legal forms / country suffixes / generic descriptors that differ between sites for one employer.
COMPANY_NOISE = {
    "as", "asa", "ab", "abp", "aps", "inc", "ltd", "llc", "gmbh", "plc", "corp", "corporation", "co",
    "limited", "ag", "sa", "bv", "nv", "oy", "oyj", "sf", "da", "ans", "norge", "norway", "norwegian",
    "bank", "group", "gruppen", "konsern", "konsernet", "holding", "holdings",
}
GENDER_TAG = re.compile(r"\(\s*(?:[mfwdkxh]\s*/\s*){1,3}[mfwdkxh]\s*\)|(?<!\w)(?:[mfwdkxh]\s*/\s*){2,3}[mfwdkxh](?!\w)|"
                        r"\(\s*(?:all genders|alle kjønn|gn|w/m/d|m/w/d)\s*\)", re.I)


def _words(s: str) -> list[str]:
    s = fold(s or "").casefold()
    s = re.sub(r"\ba\s*/\s*s\b", " as ", s)       # A/S
    s = re.sub(r"[^\w\s]|_", " ", s)
    return s.split()


def norm_company(name: str | None) -> str:
    words = _words(name or "")
    kept = [w for w in words if w not in COMPANY_NOISE]
    return " ".join(kept or words)


def norm_title(title: str | None) -> str:
    return " ".join(_words(GENDER_TAG.sub(" ", title or "")))


def dedupe_key(company: str | None, title: str | None) -> str | None:
    c, t = norm_company(company), norm_title(title)
    return f"{c}|{t}" if c and t else None


def _day(row) -> float:
    v = row["posted_at"] or row["first_seen_at"] or ""
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() / 86400
    except ValueError:
        return 0.0


def _tracked(row) -> bool:
    return row["status"] != "new" or bool(row["notes"])


def _rank(row):
    # tracked by the user > visible (not hidden by filters) > has a description > seen first
    return (not _tracked(row), bool(row["hidden"]), not row["description"], row["first_seen_at"] or "", row["id"])


def relink(conn: sqlite3.Connection, key: str | None) -> None:
    """Recompute duplicate_of for every row with this dedupe_key (idempotent)."""
    if not key:
        return
    rows = conn.execute("SELECT id, source, posted_at, first_seen_at, status, notes, hidden, description, "
                        "duplicate_of FROM jobs WHERE dedupe_key=?", (key,)).fetchall()
    want: dict[str, str | None] = {r["id"]: None for r in rows}
    clusters: list[list] = []
    for r in sorted(rows, key=_day):
        if clusters and _day(r) - _day(clusters[-1][0]) <= WINDOW_DAYS:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    for cl in clusters:
        if len({r["source"] for r in cl}) < 2:
            continue
        primary = min(cl, key=_rank)
        for r in cl:
            if r["id"] != primary["id"] and r["source"] != primary["source"] and not _tracked(r):
                want[r["id"]] = primary["id"]
    for r in rows:
        if r["duplicate_of"] != want[r["id"]]:
            conn.execute("UPDATE jobs SET duplicate_of=? WHERE id=?", (want[r["id"]], r["id"]))


def relink_job(conn: sqlite3.Connection, job_id: str) -> None:
    r = conn.execute("SELECT dedupe_key FROM jobs WHERE id=?", (job_id,)).fetchone()
    if r:
        relink(conn, r["dedupe_key"])


def set_key(conn: sqlite3.Connection, job_id: str) -> str | None:
    r = conn.execute("SELECT company, title, dedupe_key FROM jobs WHERE id=?", (job_id,)).fetchone()
    if r is None:
        return None
    key = dedupe_key(r["company"], r["title"])
    if key != r["dedupe_key"]:
        conn.execute("UPDATE jobs SET dedupe_key=? WHERE id=?", (key, job_id))
        if r["dedupe_key"]:
            relink(conn, r["dedupe_key"])  # the old group may lose a member
    return key


def dedupe_all(conn: sqlite3.Connection) -> int:
    """Fill dedupe_key for every row and link duplicates. Returns # rows marked as duplicates."""
    for r in conn.execute("SELECT id, company, title FROM jobs").fetchall():
        conn.execute("UPDATE jobs SET dedupe_key=? WHERE id=?", (dedupe_key(r["company"], r["title"]), r["id"]))
    for (key,) in conn.execute("SELECT dedupe_key FROM jobs WHERE dedupe_key IS NOT NULL "
                               "GROUP BY dedupe_key HAVING COUNT(DISTINCT source) > 1").fetchall():
        relink(conn, key)
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE duplicate_of IS NOT NULL").fetchone()[0]
