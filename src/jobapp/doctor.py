"""Health checks with plain-English fix hints."""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import asdict, dataclass

from . import config as config_mod
from . import db, paths
from .tools import which

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
DEPS = ["typer", "rich", "pydantic", "yaml", "httpx", "bs4", "fastapi", "uvicorn",
        "mcp", "docx", "pypdf", "keyring"]


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_python() -> Check:
    v = sys.version_info
    s = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 10):
        return Check("Python", FAIL, s, "Python 3.10 or newer is needed. On a Mac: 'brew install python' or use 'uv'.")
    return Check("Python", OK, s)


def check_deps() -> Check:
    missing = []
    for m in DEPS:
        try:
            importlib.import_module(m)
        except Exception:
            missing.append(m)
    if missing:
        return Check("Python packages", FAIL, "missing: " + ", ".join(missing),
                     "Run 'uv sync' in the JobApplication folder (or 'pip install -e .').")
    return Check("Python packages", OK, "all installed")


def check_tex() -> Check:
    from .resume.tex import detect
    e = detect()
    if e is None:
        return Check("LaTeX engine", FAIL, "none found",
                     "Needed to make PDFs. On a Mac: 'brew install tectonic'. On Linux: install texlive or tectonic.")
    return Check("LaTeX engine", OK, f"{e.name} ({e.path})")


def check_pandoc() -> Check:
    p = which("pandoc")
    if not p:
        return Check("pandoc", WARN, "not found",
                     "Only needed to import a Word resume. On a Mac: 'brew install pandoc'. "
                     "Without it a simpler reader is used.")
    return Check("pandoc", OK, p)


def check_pdftotext() -> Check:
    p = which("pdftotext")
    if not p:
        return Check("pdftotext", INFO, "not found — using the built-in PDF reader instead",
                     "Optional. On a Mac: 'brew install poppler'.")
    return Check("pdftotext", OK, p)


def check_config() -> tuple[Check, config_mod.Config | None]:
    try:
        cfg = config_mod.load()
    except config_mod.ConfigError as e:
        return Check("Settings (config.yaml)", FAIL, "; ".join(e.problems),
                     "Fix the line(s) above in config.yaml, then run 'jobapp config validate'. "
                     "If the file is missing run 'jobapp init'."), None
    return Check("Settings (config.yaml)", OK, str(paths.config_path())), cfg


def check_resume(cfg: config_mod.Config) -> Check:
    tex = cfg.resolve(cfg.resume.tex)
    kw = cfg.resolve(cfg.resume.keywords)
    if not tex.exists():
        return Check("Resume", FAIL, f"{tex} not found",
                     "Put your resume at that path, or import a Word file with 'jobapp resume import'.")
    if not kw.exists():
        return Check("Resume", FAIL, f"{kw} not found", "Create a keyword list (copy the example from 'jobapp init').")
    try:
        from .resume.build import check_markers
        check_markers(tex.read_text(encoding="utf-8"))
    except ImportError:
        pass
    except ValueError as e:
        return Check("Resume", FAIL, str(e),
                     "The resume needs the SKILLS marker comments so the Skills lines can be tailored.")
    return Check("Resume", OK, str(tex))


def check_db() -> Check:
    p = paths.db_path()
    if not p.exists():
        return Check("Database", WARN, "not created yet", "Run 'jobapp init'.")
    try:
        conn = db.connect(p, do_migrate=False)
        v = db.schema_version(conn)
        conn.close()
    except Exception as e:  # noqa: BLE001
        return Check("Database", FAIL, str(e), "The database file may be damaged. Use 'jobapp report-bug'.")
    want = db.latest_version()
    if v < want:
        return Check("Database", WARN, f"version {v}, latest {want}", "Run 'jobapp migrate'.")
    return Check("Database", OK, f"version {v}")


def local_time(iso: str) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(iso)[:16]


def check_last_runs() -> list[Check]:
    p = paths.db_path()
    if not p.exists():
        return []
    conn = db.connect(p)
    rows = conn.execute(
        "SELECT source, MAX(id) AS id FROM runs GROUP BY source").fetchall()
    out = []
    for r in rows:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (r["id"],)).fetchone()
        errs = json.loads(run["errors"]) if run["errors"] else []
        name = f"Last search: {run['source']}"
        when = local_time(run["finished_at"] or run["started_at"])
        if errs:
            out.append(Check(name, WARN, f"{when}: {errs[0]}" + (f" (+{len(errs)-1} more)" if len(errs) > 1 else ""),
                             "Usually temporary (site busy). If it keeps happening, run 'jobapp report-bug'."))
        else:
            out.append(Check(name, OK, f"{when}: {run['fetched']} found, {run['new']} new"))
    conn.close()
    return out


def check_sources(cfg: config_mod.Config, network: bool) -> list[Check]:
    try:
        from .sources import doctor_checks
    except ImportError:
        return []
    return doctor_checks(cfg, network)


def check_connectors(cfg: config_mod.Config) -> list[Check]:
    try:
        from .connectors import doctor_checks
    except ImportError:
        return []
    return doctor_checks(cfg)


def run(network: bool = True) -> list[Check]:
    checks = [check_python(), check_deps(), check_tex(), check_pandoc(), check_pdftotext()]
    c, cfg = check_config()
    checks.append(c)
    if cfg:
        checks.append(check_resume(cfg))
    checks.append(check_db())
    checks += check_last_runs()
    if cfg:
        checks += check_sources(cfg, network)
        checks += check_connectors(cfg)
    return checks


def summary(checks: list[Check]) -> str:
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    if fails:
        return f"{fails} problem(s) need fixing" + (f", {warns} warning(s)" if warns else "") + "."
    if warns:
        return f"Everything important works. {warns} warning(s)."
    return "Everything looks good."
