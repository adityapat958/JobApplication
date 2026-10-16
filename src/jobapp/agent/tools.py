"""Plain functions behind the MCP tools (testable without MCP). All return JSON-able dicts with
plain-English messages — never raw tracebacks."""
from __future__ import annotations

import functools
import threading
import time
import traceback
from typing import Any

from .. import config as config_mod
from .. import db, paths
from ..log import get

log = get("mcp")
LIST_KEYS = ("id", "company", "title", "location", "source", "posted_at", "match_pct", "status", "url")

_poll_state: dict[str, Any] = {"running": False, "started": None, "result": None, "error": None}
_poll_lock = threading.Lock()


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except config_mod.ConfigError as e:
            return {"ok": False, "error": "Settings problem: " + "; ".join(e.problems),
                    "hint": "Fix config.yaml (or use update_config_filters) and try again."}
        except Exception as e:  # noqa: BLE001
            log.error("tool %s failed: %s", fn.__name__, traceback.format_exc())
            msg = getattr(e, "user_message", None) or str(e) or e.__class__.__name__
            return {"ok": False, "error": msg, "hint": "Details are in the log; 'jobapp report-bug' packages them."}
    return wrapper


def _cfg():
    return config_mod.load()


def _conn():
    if not paths.config_path().exists():
        raise RuntimeError("No profile yet — run 'jobapp init' first.")
    return db.connect()


@_safe
def find_jobs(source: str | None = None, wait_seconds: int = 45) -> dict:
    """Search the job sites now (or check on a search already running)."""
    from ..poll import run_poll
    cfg = _cfg()
    with _poll_lock:
        if not _poll_state["running"] and (_poll_state["result"] is None or _poll_state.get("consumed")):
            _poll_state.update(running=True, started=time.time(), result=None, error=None, consumed=False)

            def work():
                try:
                    res = run_poll(cfg, db.connect(), only=source)
                    _poll_state["result"] = [
                        {"site": r.source, "found": r.fetched, "match_filters": r.kept, "new": r.new,
                         "problems": r.errors} for r in res]
                except Exception as e:  # noqa: BLE001
                    log.error("poll failed: %s", traceback.format_exc())
                    _poll_state["error"] = getattr(e, "user_message", None) or str(e)
                finally:
                    _poll_state["running"] = False
            threading.Thread(target=work, daemon=True).start()
    deadline = time.time() + max(0, wait_seconds)
    while _poll_state["running"] and time.time() < deadline:
        time.sleep(0.5)
    if _poll_state["running"]:
        return {"ok": True, "status": "running",
                "message": f"Still searching ({int(time.time() - _poll_state['started'])} s so far). "
                           "Call find_jobs again in a minute to get the result."}
    _poll_state["consumed"] = True
    if _poll_state["error"]:
        return {"ok": False, "error": _poll_state["error"]}
    return {"ok": True, "status": "done", "results": _poll_state["result"],
            "next": "Use list_jobs to see the best matches."}


@_safe
def list_jobs(status: str | None = None, min_match: float | None = None, search: str | None = None,
              sort: str = "match", limit: int = 20, show_hidden: bool = False) -> dict:
    """List saved jobs (best match first by default)."""
    conn = _conn()
    rows = db.list_jobs(conn, status=status, min_match=min_match, query=search, order=sort, limit=limit,
                        only_hidden=show_hidden)
    jobs = []
    for r in rows:
        j = {k: r.get(k) for k in LIST_KEYS}
        if show_hidden:
            j["why_hidden"] = r.get("hidden_reason")
        if r.get("description") is None:
            j["note"] = "no job description saved (match uses the title only)"
        jobs.append(j)
    c = db.counts(conn)
    return {"ok": True, "count": len(jobs), "total_saved": c["total"], "hidden_by_filters": c["hidden"],
            "jobs": jobs}


@_safe
def job_details(job_id: str) -> dict:
    """Everything about one job, including the description and keyword match."""
    conn = _conn()
    j = db.get_job(conn, job_id)
    if not j:
        return {"ok": False, "error": f"No job with id '{job_id}'."}
    j.pop("raw", None)
    if j.get("description") and len(j["description"]) > 6000:
        j["description"] = j["description"][:6000] + " …"
    j["last_build"] = db.last_build(conn, j["id"])
    return {"ok": True, "job": j}


@_safe
def build_resume(job_id: str) -> dict:
    """Build the tailored PDF resume for a job."""
    from ..resume.service import build_for_job
    res = build_for_job(_cfg(), _conn(), job_id)
    return {"ok": True, "pdf": str(res.pdf), "pages": res.pages, "matched_keywords": res.matched,
            "in_ad_not_in_your_keywords": res.missing[:15], "warnings": res.warnings}


@_safe
def mark_job(job_id: str, status: str) -> dict:
    """Set status: new, interested, applied, interview, rejected, offer, ignored."""
    from ..connectors import notify_updated
    conn = _conn()
    j = db.get_job(conn, job_id)
    if not j:
        return {"ok": False, "error": f"No job with id '{job_id}'."}
    old = j["status"]
    j = db.set_status(conn, j["id"], status)
    if status != "new" and j["hidden"]:
        db.set_hidden(conn, j["id"], False)
    notify_updated(_cfg(), j, {"status": [old, status]})
    return {"ok": True, "job": f"{j['company']} — {j['title']}", "status": status}


@_safe
def import_resume_prepare(docx_path: str) -> dict:
    """Start a resume import from a Word (.docx) or PDF file (docx_path = path to either): returns the prompt to follow."""
    from ..resume import docx_import as di
    p = di.prepare(docx_path)
    return {"ok": True, "prompt_file": str(p), "prompt": p.read_text(encoding="utf-8"),
            "next": "Write the full LaTeX following the prompt, then call import_resume_submit_tex with it."}


@_safe
def import_resume_submit_tex(tex: str, accept_if_ok: bool = False) -> dict:
    """Check a LaTeX version of the imported resume against the source Word or PDF file."""
    from ..resume import docx_import as di
    di.candidate_path().parent.mkdir(parents=True, exist_ok=True)
    di.candidate_path().write_text(di.extract_latex(tex), encoding="utf-8")
    rep = di.verify()
    out = {"ok": True, "passed": rep.ok, "round": rep.round, "max_rounds": di.MAX_ROUNDS,
           "checks": [{"name": g.name, "ok": g.ok, "detail": g.detail} for g in rep.gates],
           "warnings": rep.warnings}
    if not rep.ok:
        out["fix_report"] = rep.fix_report()
        out["next"] = ("Fix ONLY the listed problems and submit again." if rep.round < di.MAX_ROUNDS else
                       "Three rounds failed — stop and tell the user; suggest 'jobapp report-bug'.")
    elif accept_if_ok:
        out["installed_as"] = str(di.accept())
    else:
        out["next"] = "Show the user the result; call again with accept_if_ok=true to make it their resume."
    return out


@_safe
def doctor(check_sites: bool = True) -> dict:
    """Check the installation and settings; each problem has a fix hint."""
    from .. import doctor as d
    checks = d.run(network=check_sites)
    return {"ok": True, "summary": d.summary(checks), "checks": [c.to_dict() for c in checks]}


FILTER_FIELDS = ("title_include", "title_exclude", "locations", "job_types", "max_age_days",
                 "companies_include", "companies_exclude", "languages")


@_safe
def update_config_filters(title_include: list[str] | None = None, title_exclude: list[str] | None = None,
                          locations: list[str] | None = None, job_types: list[str] | None = None,
                          max_age_days: int | None = None, companies_include: list[str] | None = None,
                          companies_exclude: list[str] | None = None, languages: list[str] | None = None) -> dict:
    """Change the job filters in config.yaml (only the fields you pass). Old file kept as config.yaml.bak."""
    import shutil
    vals = dict(title_include=title_include, title_exclude=title_exclude, locations=locations,
                job_types=job_types, max_age_days=max_age_days, companies_include=companies_include,
                companies_exclude=companies_exclude, languages=languages)
    changes = {k: v for k, v in vals.items() if v is not None}
    if not changes:
        return {"ok": False, "error": "Nothing to change — pass at least one filter field."}
    cfg = _cfg()
    data = cfg.model_dump(mode="json")
    data["filters"].update(changes)
    new = config_mod.parse(data)  # validates; raises ConfigError with friendly text
    p = paths.config_path()
    shutil.copy2(p, p.with_suffix(".yaml.bak"))
    config_mod.save(new, p)
    from ..poll import refilter_all
    n = refilter_all(_conn(), new)
    return {"ok": True, "changed": changes, "jobs_reclassified": n,
            "filters_now": new.filters.model_dump(mode="json")}


ALL = [find_jobs, list_jobs, job_details, build_resume, mark_job, import_resume_prepare,
       import_resume_submit_tex, doctor, update_config_filters]
