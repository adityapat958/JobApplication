"""Import jobs from the older Mongo-based tracker ("jobdesk": database `jobdesk`, collection `jobs`).

Read-only on the Mongo side. Each old document becomes one row; the old id is kept in `legacy_id` (rerun =
no changes: rows already imported are left exactly as they are). LinkedIn jobs get their LinkedIn job id as
source_id, so a new poll finds the same row. Simplify jobs without a stable id get `legacy:<old id>` and are
adopted by the first poll that lists the same apply URL (db.find_existing). Contacts and messages are not
imported.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from .db import dedupe as dd
from .models import STATUSES, job_id
from .text import clean, detect_language, normalize_job_type

SOURCE_MAP = {"linkedin": "linkedin", "simplifyjobs": "simplify", "simplify_github": "simplify",
              "simplify": "simplify", "finn": "finn", "jobright": "jobright", "manual": "manual", "": "legacy"}
LEGACY_KEYS = ("id", "source", "tier", "needs_manual", "variant", "match_score", "build_count", "last_built",
               "gaps", "date_found")


class MongoImportError(RuntimeError):
    pass


def _iso(v) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(v, date):
        return f"{v.isoformat()}T12:00:00+00:00"
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return f"{s}T12:00:00+00:00"  # midday UTC: the same calendar day in Europe and the Americas
    try:
        return _iso(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return _iso(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def map_source(name: str | None) -> str:
    n = (name or "").strip().lower()
    return SOURCE_MAP.get(n, re.sub(r"[^a-z0-9]+", "_", n).strip("_") or "legacy")


def linkedin_id(url: str | None) -> str | None:
    if not url or "linkedin." not in url:
        return None
    m = re.search(r"/jobs/view/(\d{6,})", url) or re.search(r"[-/](\d{8,})(?:[/?#]|$)", url) \
        or re.search(r"currentJobId=(\d{6,})", url)
    return m[1] if m else None


def _from_note_name(note_path: str | None) -> tuple[str, str]:
    stem = Path(note_path or "").stem
    if " — " in stem:
        c, t = stem.split(" — ", 1)
        return c.strip(), t.strip()
    return "", stem.strip()


def doc_to_row(doc: dict, variants: list[str] | None = None) -> dict:
    """One old document → the columns of a new `jobs` row (pure; no DB)."""
    old_id = str(doc.get("id") or doc.get("_id"))
    source = map_source(doc.get("source"))
    url = (doc.get("apply_url") or doc.get("url") or "").strip()
    if not doc.get("source") and "linkedin." in url:
        source = "linkedin"
    sid = None
    if source == "linkedin":
        sid = linkedin_id(url)
    elif source == "simplify":
        m = re.search(r"simplify\.jobs/p/([0-9a-f-]{8,})", url)
        sid = m[1] if m else None
    sid = sid or f"legacy:{old_id}"
    company, title = clean(doc.get("company")), clean(doc.get("title"))
    if company in ("↳", "-", "—"):  # the old Simplify watcher stored the "same company" arrow as the name
        company = clean(doc.get("_company_hint")) or ""
    if not title:
        nc, nt = _from_note_name(doc.get("note_path"))
        company, title = company or nc, nt
    status = (doc.get("status") or "").strip().lower()
    done = bool(doc.get("done")) or status in db.DONE_STATUSES
    if status not in STATUSES:
        status = "applied" if done else "new"
    first = _iso(doc.get("date_found")) or _iso(doc.get("first_seen")) or db.now()
    done_at = _iso(doc.get("done_at")) if done else None
    if done and not done_at:
        done_at = first
    jd = doc.get("jd_body") or None
    tier = clean(doc.get("tier")) or None
    raw = {"legacy": {k: _jsonable(doc.get(k)) for k in LEGACY_KEYS if doc.get(k) not in (None, "", [])}}
    if tier:
        raw["tier"] = tier
    variant = doc.get("variant") if variants and doc.get("variant") in variants else None
    return {
        "id": job_id(source, sid), "source": source, "source_id": sid, "url": url, "apply_url": url,
        "company": company, "title": title, "location": clean(doc.get("location")),
        "job_type": normalize_job_type(doc.get("type")) or "", "posted_at": None,
        "first_seen_at": first, "last_seen_at": first, "description": jd,
        "jd_saved_at": _iso(doc.get("jd_saved_at")) if jd else None,
        "language": detect_language(jd) if jd else None, "raw": json.dumps(raw, ensure_ascii=False),
        "status": status, "done": 1 if done else 0, "done_at": done_at,
        "status_updated_at": done_at or first, "variant": variant,
        "legacy_id": old_id, "note_path": doc.get("note_path") or None, "legacy_url_key": db.url_key(url),
    }


@dataclass
class ImportReport:
    docs: int = 0
    inserted: int = 0
    already: int = 0
    differs: int = 0
    by_source: Counter = field(default_factory=Counter)
    old_status: Counter = field(default_factory=Counter)
    new_status: Counter = field(default_factory=Counter)
    done: int = 0
    jd: int = 0
    jd_hand_saved: int = 0
    stable_ids: int = 0
    legacy_ids: int = 0
    same_listing: int = 0
    rescored: dict = field(default_factory=dict)
    not_imported: dict = field(default_factory=dict)
    dry_run: bool = False

    def lines(self) -> list[str]:
        v = "would be " if self.dry_run else ""
        out = [f"Old jobs read: {self.docs}",
               f"  {v}imported: {self.inserted}   already imported (left as they are): {self.already}"
               + (f" — {self.differs} of them changed in the old system since" if self.differs else ""),
               "  by source: " + ", ".join(f"{k}: {n}" for k, n in sorted(self.by_source.items())),
               "  status (old): " + ", ".join(f"{k or '(empty)'}: {n}" for k, n in self.old_status.most_common()),
               "  status (new): " + ", ".join(f"{k}: {n}" for k, n in self.new_status.most_common()),
               f"  done/applied: {self.done}; with a job description: {self.jd} ({self.jd_hand_saved} hand-saved)",
               f"  stable ids (a new poll finds them directly): {self.stable_ids}; matched later by apply "
               f"link: {self.legacy_ids}" + (f"; same listing twice in the old data: {self.same_listing}"
                                              if self.same_listing else "")]
        if self.rescored:
            out.append(f"  re-scored: {self.rescored.get('jobs', 0)} job(s), {self.rescored.get('changed', 0)} changed")
        if self.not_imported:
            out.append("Not imported (outreach stays in the old system): "
                       + ", ".join(f"{k}: {n}" for k, n in self.not_imported.items()))
        return out


_COLS = ("id", "source", "source_id", "url", "apply_url", "company", "title", "location", "job_type", "posted_at",
         "first_seen_at", "last_seen_at", "description", "jd_saved_at", "language", "raw", "status", "done",
         "done_at", "status_updated_at", "variant", "legacy_id", "note_path", "legacy_url_key")
_COMPARE = ("company", "title", "location", "status", "done", "description", "jd_saved_at", "note_path")


def import_docs(cfg, conn, docs, *, dry_run: bool = False, rescore: bool = True) -> ImportReport:
    rep = ImportReport(dry_run=dry_run)
    variants = list(cfg.resume.variants) if cfg is not None else []
    inserted: set[str] = set()
    # tracked jobs first, then ones with a description, then oldest: the first document of a listing wins
    docs = sorted(docs, key=lambda d: ((d.get("status") or "new") == "new" and not d.get("done"),
                                       not d.get("jd_body"), str(d.get("date_found") or "9999")))
    docs = _link_twins(docs)
    conn.execute("BEGIN")
    try:
        for doc in docs:
            rep.docs += 1
            rep.old_status[(doc.get("status") or "")] += 1
            row = doc_to_row(doc, variants)
            rep.by_source[row["source"]] += 1
            have = conn.execute("SELECT * FROM jobs WHERE legacy_id=?", (row["legacy_id"],)).fetchone()
            if have is not None:
                rep.already += 1
                rep.new_status[have["status"]] += 1
                rep.done += have["done"]
                if any((have[k] or None) != (row[k] or None) for k in _COMPARE):
                    rep.differs += 1
                continue
            taken = conn.execute("SELECT id, status, description, jd_saved_at FROM jobs WHERE source=? AND source_id=?",
                                 (row["source"], row["source_id"])).fetchone()
            if taken is None and doc.get("_twin_of"):
                taken = conn.execute("SELECT id, status, description, jd_saved_at FROM jobs WHERE legacy_id=?",
                                     (doc["_twin_of"],)).fetchone()
            if taken is not None:  # two old documents for one listing (e.g. two link styles): one row
                rep.same_listing += 1
                if taken["id"] in inserted:
                    _merge(conn, taken, row)
                continue
            conn.execute(f"INSERT INTO jobs ({', '.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
                         [row[c] for c in _COLS])
            rep.inserted += 1
            inserted.add(row["id"])
            rep.new_status[row["status"]] += 1
            rep.done += row["done"]
            rep.jd += bool(row["description"])
            rep.jd_hand_saved += bool(row["jd_saved_at"])
            if row["source_id"].startswith("legacy:"):
                rep.legacy_ids += 1
            else:
                rep.stable_ids += 1
        if rep.inserted:
            dd.dedupe_all(conn)
            if cfg is not None:
                from .poll import refilter_all
                refilter_all(conn, cfg)
        if rescore and cfg is not None:
            from .resume.rescore import rescore_all
            try:
                rep.rescored = rescore_all(cfg, conn)
            except ValueError as e:  # no keyword list yet
                rep.rescored = {"error": str(e)}
        conn.execute("ROLLBACK" if dry_run else "COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return rep


def _same_title(a: str, b: str) -> bool:
    a, b = dd.norm_title(a), dd.norm_title(b)
    return bool(a and b) and (a == b or a.startswith(b + " ") or b.startswith(a + " "))


def _link_twins(docs: list) -> list:
    """Old documents of one listing saved twice under different ids (the title was edited, or the company was
    stored as "↳"): same apply link shared by exactly these two, same place, same or extended title. The later
    one is marked `_twin_of` the first. "↳" companies are filled in from the twin. Input order is kept."""
    groups: dict = {}
    for d in docs:
        k = (map_source(d.get("source")), db.url_key(d.get("apply_url") or d.get("url")))
        if k[1]:
            groups.setdefault(k, []).append(d)
    out = [dict(d) for d in docs]
    by_id = {id(d): o for d, o in zip(docs, out)}
    for g in groups.values():
        if len(g) != 2:
            continue  # unique link, or a generic careers-page link shared by many jobs
        a, b = (by_id[id(x)] for x in g)
        if clean(a.get("location")).casefold() != clean(b.get("location")).casefold():
            continue
        if not _same_title(a.get("title") or "", b.get("title") or ""):
            continue
        ca, cb = clean(a.get("company")), clean(b.get("company"))
        if ca not in ("", "↳") and cb not in ("", "↳") and dd.norm_company(ca) != dd.norm_company(cb):
            continue
        for x, y in ((a, cb), (b, ca)):
            if y not in ("", "↳"):
                x["_company_hint"] = y
        b["_twin_of"] = str(a.get("id") or a.get("_id"))
    return out


def _merge(conn, have, row: dict) -> None:
    """Fill gaps of the row imported first for a listing from a second document of the same listing."""
    sets = {}
    if have["status"] == "new" and row["status"] != "new":
        sets.update(status=row["status"], done=row["done"], done_at=row["done_at"],
                    status_updated_at=row["status_updated_at"])
    if not have["description"] and row["description"]:
        sets.update(description=row["description"], jd_saved_at=row["jd_saved_at"], language=row["language"])
    if sets:
        conn.execute("UPDATE jobs SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?", (*sets.values(), have["id"]))


def load_docs(uri: str, dbname: str, *, timeout_ms: int = 5000) -> tuple[list[dict], dict]:
    """(job documents, {"contacts": n, "messages": n}) — read-only."""
    try:
        from pymongo import MongoClient
    except ImportError:
        raise MongoImportError("pymongo isn't installed. Run: uv sync --extra mongo  (or pip install 'jobapp[mongo]')") from None
    client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    try:
        mdb = client[dbname]
        names = set(mdb.list_collection_names())
        if "jobs" not in names:
            raise MongoImportError(f"No 'jobs' collection in Mongo database '{dbname}' at {uri}.")
        docs = list(mdb["jobs"].find({}))
        other = {n: mdb[n].estimated_document_count() for n in ("contacts", "messages") if n in names}
        return docs, other
    except MongoImportError:
        raise
    except Exception as e:  # noqa: BLE001
        raise MongoImportError(f"Couldn't read Mongo at {uri}: {e}") from None
    finally:
        client.close()
