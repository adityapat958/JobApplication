"""Run sources → filter → save → fetch JD for kept new jobs → score → notify connectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import db, sources
from .connectors import notify_added
from .filters import apply_filters
from .http import Http, HttpError
from .log import get
from .models import JobPosting
from .text import detect_language, fold, parse_iso

log = get("poll")


@dataclass
class PollResult:
    source: str
    fetched: int = 0
    kept: int = 0
    new: int = 0
    jd_fetched: int = 0
    errors: list[str] = field(default_factory=list)
    preview: list[tuple[JobPosting, bool, str]] = field(default_factory=list)


def _apply_details(job: JobPosting, info: dict) -> None:
    if info.get("description"):
        job.description = info["description"]
    if info.get("job_type") and not job.job_type:
        job.job_type = info["job_type"]
    for k in ("location", "title"):
        if info.get(k) and not getattr(job, k):
            setattr(job, k, info[k])
    # The ad page's employer (JSON-LD / labelled field) beats the search card; never keep company == title.
    if info.get("company") and fold(info["company"]) != fold(job.title or ""):
        job.company = info["company"]
    elif job.company and fold(job.company) == fold(job.title or ""):
        job.company = ""
    if info.get("posted_at") and not job.posted_at:
        job.posted_at = info["posted_at"]
    for k in ("deadline", "seniority", "employment_type", "industries"):
        if info.get(k):
            job.raw[k] = info[k]


def _details(src, job, http) -> dict:
    if hasattr(src, "fetch_details"):
        return src.fetch_details(job, http) or {}
    d = src.fetch_description(job, http)
    return {"description": d} if d else {}


def _matcher(cfg):
    try:
        from .resume.matching import Matcher
        return Matcher.from_config(cfg)
    except Exception as e:  # noqa: BLE001  (no resume/keywords yet is fine)
        log.info("matching disabled: %s", e)
        return None


def run_poll(cfg, conn, *, only: str | None = None, dry_run: bool = False, fetch_jd: bool = True,
             http: Http | None = None, progress: Callable[[str], None] | None = None,
             max_jd: int = 200) -> list[PollResult]:
    say = progress or (lambda _m: None)
    names = [only] if only else sources.enabled(cfg)
    if only:
        sources.get(only)  # validates name
    own_http = http is None
    http = http or Http()
    matcher = None if dry_run else _matcher(cfg)
    results = []
    try:
        for name in names:
            res = PollResult(name)
            results.append(res)
            src = sources.get(name)
            run_id = None if dry_run else db.start_run(conn, name)
            say(f"Searching {src.label}…")
            jd_budget = max_jd
            try:
                for job in src.fetch(cfg, http):
                    res.fetched += 1
                    keep, why = apply_filters(job, cfg.filters)
                    if dry_run:
                        res.preview.append((job, keep, why))
                        res.kept += keep
                        continue
                    existing = conn.execute("SELECT id, description, jd_saved_at FROM jobs WHERE source=? AND source_id=?",
                                            (job.source, job.source_id)).fetchone()
                    need_jd = keep and fetch_jd and jd_budget > 0 and (
                        existing is None or (not existing["description"] and not existing["jd_saved_at"]))
                    if need_jd:
                        jd_budget -= 1
                        try:
                            info = _details(src, job, http)
                        except HttpError as e:
                            info = {}
                            log.info("JD fetch %s failed: %s", job.source_id, e)
                        if info.get("description"):
                            res.jd_fetched += 1
                        _apply_details(job, info)
                        keep, why = apply_filters(job, cfg.filters)  # type/language may be known now
                    if job.description and not job.language:
                        job.language = detect_language(job.description)
                    jid, is_new = db.upsert_job(conn, job)
                    row = db.get_job(conn, jid)
                    if row["status"] != "new":
                        keep, why = True, ""  # never hide a job the user is tracking
                    db.set_hidden(conn, jid, not keep, why)
                    res.kept += keep
                    res.new += is_new
                    if matcher and (is_new or need_jd):
                        matcher.score_and_save(conn, row)
                    if is_new:
                        notify_added(cfg, db.get_job(conn, jid))
            except sources.NeedsLogin as e:
                res.errors.append(str(e))
            except (HttpError, ValueError) as e:
                res.errors.append(f"{src.label}: {e}")
            except Exception as e:  # noqa: BLE001
                log.exception("source %s crashed", name)
                res.errors.append(f"{src.label}: unexpected problem ({e.__class__.__name__}: {e})")
            if not dry_run:
                db.finish_run(conn, run_id, res.fetched, res.new, res.errors)
        if not dry_run and not only:
            refilter_all(conn, cfg)
    finally:
        if own_http:
            http.close()
    return results


def refilter_all(conn, cfg) -> int:
    """Re-apply current filters to every saved job (so config changes take effect). Returns # changed."""
    changed = 0
    for row in conn.execute("SELECT id, title, company, location, job_type, posted_at, first_seen_at, "
                            "language, description, hidden, hidden_reason, status FROM jobs"):
        job = dict(row)
        job["posted_at"] = parse_iso(job["posted_at"]) or parse_iso(job["first_seen_at"])
        keep, why = apply_filters(job, cfg.filters) if row["status"] == "new" else (True, "")
        if (not keep) != bool(row["hidden"]) or (not keep and why != row["hidden_reason"]):
            db.set_hidden(conn, row["id"], not keep, why)
            changed += 1
    return changed
