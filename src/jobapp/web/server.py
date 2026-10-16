"""Local dashboard (FastAPI). Bound to 127.0.0.1 only.

State-changing requests must carry the header `X-JobApp: 1` (a browser on another site can't add it
without a CORS preflight, which we never allow) and the Host must be localhost — this blocks
cross-site requests and DNS rebinding.
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import __version__, db, paths
from .. import config as config_mod
from ..log import get
from ..models import STATUSES
from ..platform import folder_label, reveal

log = get("web")
HERE = Path(__file__).parent
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
LIST_FIELDS = ("id", "source", "company", "title", "location", "job_type", "posted_at", "first_seen_at",
               "match_pct", "title_score", "matched", "status", "done", "hidden", "hidden_reason", "url", "apply_url",
               "jd_saved_at", "notes")

_refresh = {"running": False, "last": None, "summary": "", "error": None}
_refresh_lock = threading.Lock()


def create_app(poll_fn=None) -> FastAPI:
    app = FastAPI(title="JobApplication", version=__version__, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS and host != "testserver":
            return JSONResponse({"ok": False, "error": "forbidden host"}, status_code=403)
        if request.method not in ("GET", "HEAD") and request.headers.get("x-jobapp") != "1":
            return JSONResponse({"ok": False, "error": "missing X-JobApp header"}, status_code=403)
        return await call_next(request)

    def cfg():
        try:
            return config_mod.load()
        except config_mod.ConfigError as e:
            raise HTTPException(400, "Settings problem: " + "; ".join(e.problems))

    def conn():
        return db.connect()

    def job_or_404(c, job_id):
        j = db.get_job(c, job_id)
        if not j:
            raise HTTPException(404, "unknown job")
        return j

    @app.exception_handler(HTTPException)
    async def http_err(_req, exc: HTTPException):
        return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (HERE / "index.html").read_text(encoding="utf-8").replace("{{FOLDER_LABEL}}", folder_label())

    @app.get("/job/{job_id}", response_class=HTMLResponse)
    def job_page(job_id: str):
        c = conn()
        job_or_404(c, job_id)
        return (HERE / "job.html").read_text(encoding="utf-8").replace("{{JOB_ID}}", job_id)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/jobs")
    def jobs(hidden: bool = True):
        c = conn()
        rows = db.list_jobs(c, include_hidden=hidden, order="match", title_include=config_mod.title_include())
        return [{k: r.get(k) for k in LIST_FIELDS} for r in rows]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        c = conn()
        j = job_or_404(c, job_id)
        j.pop("raw", None)
        j["last_build"] = db.last_build(c, j["id"])
        return j

    @app.post("/api/jobs/{job_id}/status")
    def set_status(job_id: str, payload: dict = Body(...)):
        status = payload.get("status")
        if status not in STATUSES:
            raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")
        c = conn()
        old = job_or_404(c, job_id)["status"]
        j = db.set_status(c, job_id, status)
        if j["hidden"] and status != "new":
            db.set_hidden(c, job_id, False)  # a job you're tracking is never hidden
        from ..connectors import notify_updated
        notify_updated(cfg(), db.get_job(c, job_id), {"status": [old, status]})
        return {"ok": True, "status": j["status"], "done": j["done"]}

    @app.post("/api/jobs/{job_id}/notes")
    def set_notes(job_id: str, payload: dict = Body(...)):
        c = conn()
        job_or_404(c, job_id)
        db.set_notes(c, job_id, str(payload.get("notes", ""))[:20000])
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/description")
    def set_description(job_id: str, payload: dict = Body(...)):
        text = str(payload.get("description", "")).strip()
        c = conn()
        job_or_404(c, job_id)
        db.set_description(c, job_id, text or None, manual=True)
        result = {"ok": True}
        try:
            from ..resume.matching import Matcher
            r = Matcher.from_config(cfg()).score_and_save(c, db.get_job(c, job_id))
            result.update(match_pct=r.pct, matched=r.matched, missing=r.missing)
        except ValueError as e:
            result["warning"] = str(e)
        return result

    @app.post("/api/build/{job_id}")
    def build(job_id: str):
        from ..resume.service import BuildError, build_for_job
        c = conn()
        job_or_404(c, job_id)
        try:
            res = build_for_job(cfg(), c, job_id)
        except BuildError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
        return {"ok": True, "pdf_url": f"/api/pdf/{job_id}", "filename": res.pdf.name, "path": str(res.pdf),
                "matched": res.matched, "missing": res.missing[:15], "warnings": res.warnings, "pages": res.pages}

    def _pdf_path(c, job_id) -> Path:
        b = db.last_build(c, job_or_404(c, job_id)["id"])
        if not b or not Path(b["pdf_path"]).exists():
            raise HTTPException(404, "No resume built for this job yet.")
        p = Path(b["pdf_path"]).resolve()
        if paths.output_dir().resolve() not in p.parents:
            raise HTTPException(403, "file outside output folder")
        return p

    @app.get("/api/pdf/{job_id}")
    def pdf(job_id: str):
        p = _pdf_path(conn(), job_id)
        return FileResponse(p, media_type="application/pdf", filename=p.name)

    @app.post("/api/reveal/{job_id}")
    def reveal_pdf(job_id: str):
        p = _pdf_path(conn(), job_id)
        return {"ok": reveal(p), "path": str(p)}

    @app.get("/api/refresh")
    def refresh_status():
        return dict(_refresh)

    @app.post("/api/refresh")
    def refresh_start():
        with _refresh_lock:
            if _refresh["running"]:
                return {"ok": True, "already": True}
            _refresh.update(running=True, error=None)
        c = cfg()

        def work():
            from datetime import datetime
            try:
                fn = poll_fn
                if fn is None:
                    from ..poll import run_poll as fn
                cn = db.connect()
                res = fn(c, cn)
                _refresh["summary"] = "; ".join(f"{r.source}: {r.new} new" for r in res)
                errs = [e for r in res for e in r.errors]
                _refresh["error"] = errs[0] if errs else None
            except Exception as e:  # noqa: BLE001
                log.exception("refresh failed")
                _refresh["error"] = str(e)
            finally:
                _refresh["running"] = False
                _refresh["last"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    @app.get("/api/stats")
    def stats():
        c = conn()
        out = db.counts(c)
        runs = db.last_runs(c, 1)
        out["last_run"] = runs[0]["finished_at"] if runs else None
        return out

    return app


def serve(port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn
    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Dashboard running at {url}  (press Ctrl+C to stop)")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
