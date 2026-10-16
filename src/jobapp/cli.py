"""Command line interface. Plain English output; tracebacks go to the log file only."""
from __future__ import annotations

import json
import sys
import traceback
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, paths
from . import config as config_mod
from . import log as logmod

app = typer.Typer(add_completion=False, no_args_is_help=True, pretty_exceptions_enable=False,
                  help="JobApplication — find jobs, filter them, and build a tailored resume for each.")
config_app = typer.Typer(no_args_is_help=True, help="Check or show your settings.")
resume_app = typer.Typer(no_args_is_help=True, help="Your resume: import from Word.")
schedule_app = typer.Typer(no_args_is_help=True, help="Run job searches automatically.")
app.add_typer(config_app, name="config")
app.add_typer(resume_app, name="resume")
app.add_typer(schedule_app, name="schedule")

con = Console()
err = Console(stderr=True)


class UserError(Exception):
    """An error with a message meant for the user (no traceback)."""


def _cfg() -> config_mod.Config:
    try:
        return config_mod.load()
    except config_mod.ConfigError as e:
        raise UserError("Your settings have a problem:\n  - " + "\n  - ".join(e.problems))


def _conn():
    from . import db
    if not paths.config_path().exists():
        raise UserError("No profile yet. Run 'jobapp init' first.")
    return db.connect()


# ── basics ────────────────────────────────────────────────
@app.command()
def version():
    """Show the version."""
    con.print(f"jobapp {__version__}")


@app.command()
def init(force: bool = typer.Option(False, "--force", help="Overwrite files with the example versions.")):
    """Create your personal data folder (settings, example resume, database)."""
    from . import profile
    home, created = profile.init(force=force)
    con.print(f"Your data folder: [bold]{home}[/bold]")
    if created:
        for c in created:
            con.print(f"  created {c}")
    else:
        con.print("  everything was already there (nothing changed)")
    con.print("Next: edit config.yaml (or ask Claude to), then run [bold]jobapp doctor[/bold].")


@app.command()
def migrate():
    """Update the database to the latest version (safe to run any time)."""
    from . import db
    conn = _conn()
    con.print(f"Database is at version {db.schema_version(conn)}.")


@config_app.command("validate")
def config_validate():
    """Check config.yaml and explain any mistakes."""
    try:
        cfg = config_mod.load()
    except config_mod.ConfigError as e:
        con.print("[red]Your settings have a problem:[/red]")
        for p in e.problems:
            con.print(f"  - {p}")
        raise typer.Exit(1)
    enabled = [n for n, s in cfg.sources if getattr(s, "enabled", False)]
    con.print(f"[green]Settings look good.[/green] Job sites switched on: {', '.join(enabled) or 'none'}")


@config_app.command("show")
def config_show():
    """Print your current settings."""
    import yaml
    cfg = _cfg()
    con.print(f"# {paths.config_path()}")
    con.print(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True))


@app.command()
def doctor(offline: bool = typer.Option(False, "--offline", help="Skip checking that job sites respond."),
           as_json: bool = typer.Option(False, "--json", help="Machine-readable output.")):
    """Check that everything is installed and working."""
    from . import doctor as d
    checks = d.run(network=not offline)
    if as_json:
        print(json.dumps([c.to_dict() for c in checks], indent=2))
        return
    icon = {"ok": "[green]✔[/green]", "warn": "[yellow]![/yellow]", "fail": "[red]✘[/red]", "info": "[blue]i[/blue]"}
    for c in checks:
        con.print(f"{icon[c.status]} [bold]{c.name}[/bold]: {c.detail}")
        if c.hint and c.status != "ok":
            con.print(f"    → {c.hint}")
    con.print()
    con.print(d.summary(checks))
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


# ── jobs ──────────────────────────────────────────────────
@app.command()
def poll(source: Optional[str] = typer.Option(None, "--source", help="Only this job site."),
         dry_run: bool = typer.Option(False, "--dry-run", help="Fetch and show, but don't save."),
         no_jd: bool = typer.Option(False, "--no-jd", help="Skip downloading full job descriptions.")):
    """Search the job sites now."""
    from .poll import run_poll
    cfg = _cfg()
    conn = None if dry_run else _conn()
    res = run_poll(cfg, conn, only=source, dry_run=dry_run, fetch_jd=not no_jd, progress=con.print)
    for r in res:
        line = f"[bold]{r.source}[/bold]: {r.fetched} found, {r.kept} match your filters, {r.new} new"
        con.print(line)
        for e in r.errors:
            con.print(f"  [yellow]![/yellow] {e}")
    if dry_run:
        for r in res:
            for j, keep, why in r.preview[:30]:
                mark = "[green]keep[/green]" if keep else f"[dim]hide ({why})[/dim]"
                con.print(f"  {mark} {j.company} — {j.title} — {j.location}")


@app.command("list")
def list_cmd(status: Optional[str] = typer.Option(None, "--status"),
             min_match: Optional[float] = typer.Option(None, "--min-match"),
             hidden: bool = typer.Option(False, "--hidden", help="Show jobs your filters hid, with the reason."),
             search: Optional[str] = typer.Option(None, "--search", "-q"),
             sort: str = typer.Option("newest", "--sort", help="newest | match | company"),
             limit: int = typer.Option(50, "--limit"),
             as_json: bool = typer.Option(False, "--json")):
    """List saved jobs."""
    from . import db
    conn = _conn()
    rows = db.list_jobs(conn, status=status, min_match=min_match, only_hidden=hidden, query=search,
                        order=sort, limit=limit)
    if as_json:
        print(json.dumps([{k: r[k] for k in ("id", "company", "title", "location", "source", "posted_at",
                                              "match_pct", "status", "hidden_reason", "url")} for r in rows],
                         indent=2, ensure_ascii=False))
        return
    if not rows:
        con.print("No jobs yet." if not hidden else "No hidden jobs.")
        return
    t = Table(show_lines=False)
    for col in ("id", "company", "title", "location", "source", "posted", "match", "status"):
        t.add_column(col)
    if hidden:
        t.add_column("why hidden")
    for r in rows:
        posted = (r["posted_at"] or r["first_seen_at"] or "")[:10]
        match = "" if r["match_pct"] is None else f"{r['match_pct']:.0f}%"
        cells = [r["id"], r["company"] or "", r["title"] or "", r["location"] or "", r["source"], posted,
                 match, r["status"]]
        if hidden:
            cells.append(r["hidden_reason"] or "")
        t.add_row(*cells)
    con.print(t)


@app.command()
def show(job_id: str):
    """Show one job in detail."""
    from . import db
    conn = _conn()
    j = db.get_job(conn, job_id)
    if not j:
        raise UserError(f"No job with id '{job_id}'. Use 'jobapp list' to see ids.")
    con.print(f"[bold]{j['company']} — {j['title']}[/bold]  ({j['id']})")
    for k in ("location", "job_type", "source", "posted_at", "first_seen_at", "status", "url", "apply_url"):
        if j.get(k):
            con.print(f"  {k}: {j[k]}")
    if j.get("match_pct") is not None:
        con.print(f"  match: {j['match_pct']:.0f}%")
        con.print(f"  matched: {', '.join(j['matched']) or '-'}")
        con.print(f"  missing: {', '.join(j['missing']) or '-'}")
    if j.get("hidden"):
        con.print(f"  hidden by filters: {j['hidden_reason']}")
    if j.get("notes"):
        con.print(f"  notes: {j['notes']}")
    desc = j.get("description")
    con.print()
    con.print(desc[:3000] + ("…" if len(desc) > 3000 else "") if desc else
              "[yellow](No job description saved — paste it in the dashboard for a better match.)[/yellow]")


@app.command()
def mark(job_id: str, status: str):
    """Set a job's status: new, interested, applied, interview, rejected, offer, ignored."""
    from . import db
    from .models import STATUSES
    if status not in STATUSES:
        import difflib
        g = difflib.get_close_matches(status, STATUSES, n=1)
        raise UserError(f"'{status}' isn't a status. Use one of: {', '.join(STATUSES)}"
                        + (f" (did you mean '{g[0]}'?)" if g else ""))
    conn = _conn()
    j = db.get_job(conn, job_id)
    if not j:
        raise UserError(f"No job with id '{job_id}'.")
    old = j["status"]
    j = db.set_status(conn, j["id"], status)
    from .connectors import notify_updated
    notify_updated(_cfg(), j, {"status": [old, status]})
    con.print(f"{j['company']} — {j['title']}: [bold]{status}[/bold]")


@app.command()
def rescore():
    """Re-score every saved job against your keyword list (after you edit keywords.yaml)."""
    from . import db
    from .resume.matching import Matcher
    cfg = _cfg()
    try:
        m = Matcher.from_config(cfg)
    except ValueError as e:
        raise UserError(str(e))
    conn = _conn()
    rows = db.list_jobs(conn, include_hidden=True)
    for r in rows:
        m.score_and_save(conn, r)
    con.print(f"Re-scored {len(rows)} job(s).")


@app.command()
def build(job_id: str, reveal: bool = typer.Option(False, "--reveal", help="Show the PDF in Finder/file manager.")):
    """Build a tailored resume PDF for one job."""
    from .resume.service import build_for_job
    cfg = _cfg()
    conn = _conn()
    res = build_for_job(cfg, conn, job_id)
    con.print(f"[green]PDF ready:[/green] {res.pdf}")
    con.print(f"  matched {len(res.matched)} keyword(s): {', '.join(res.matched[:12]) or '-'}")
    if res.missing:
        con.print(f"  in the ad but not in your keyword list: {', '.join(res.missing[:10])}")
    for w in res.warnings:
        con.print(f"  [yellow]![/yellow] {w}")
    if reveal:
        from .platform import reveal as rv
        rv(res.pdf)


@app.command()
def serve(port: int = typer.Option(8765, "--port"), open_browser: bool = typer.Option(True, "--open/--no-open")):
    """Open the dashboard in your browser (http://127.0.0.1:8765)."""
    from .web.server import serve as srv
    _cfg()
    srv(port=port, open_browser=open_browser)


@app.command()
def mcp():
    """Run the MCP server for Claude Desktop (stdio)."""
    from .agent.mcp_server import main as mcp_main
    mcp_main()


@app.command("report-bug")
def report_bug():
    """Make a zip with logs and diagnostics (personal details removed) to send to the developer."""
    from .bugreport import make_report
    p = make_report()
    con.print(f"Bug report saved: [bold]{p}[/bold]")
    con.print("Names, emails, phone numbers and passwords were removed. You can open the zip to check.")


# ── resume import ─────────────────────────────────────────
@resume_app.command("import")
def resume_import(docx: Optional[str] = typer.Argument(None, help="Your Word resume (.docx)."),
                  prepare: bool = typer.Option(False, "--prepare", help="Write import/prompt.md for Claude."),
                  verify: bool = typer.Option(False, "--verify", help="Check import/resume.tex against the Word file."),
                  accept: bool = typer.Option(False, "--accept", help="After a passing verify, use it as your resume."),
                  api: bool = typer.Option(False, "--api", help="Do the whole loop with an API key.")):
    """Turn a Word resume into the LaTeX template (Claude does the typing, code checks it)."""
    from .resume import docx_import as di
    if verify or accept:
        rep = di.verify()
        con.print(rep.summary())
        if not rep.ok:
            con.print(f"Fix list written to [bold]{di.fix_report_path()}[/bold]")
            raise typer.Exit(1)
        if accept:
            dst = di.accept()
            con.print(f"[green]Your resume is now[/green] {dst}")
        return
    if not docx:
        raise UserError("Give the Word file, e.g.: jobapp resume import ~/Desktop/resume.docx --prepare")
    if api:
        rep = di.run_api(docx)
        con.print(rep.summary())
        raise typer.Exit(0 if rep.ok else 1)
    p = di.prepare(docx)
    con.print(f"Prompt written: [bold]{p}[/bold]")
    con.print(f"Next: write the LaTeX to {di.candidate_path()} and run 'jobapp resume import --verify'.")


# ── schedule ──────────────────────────────────────────────
@schedule_app.command("install")
def schedule_install():
    """Search for jobs automatically at the times in config.yaml."""
    from . import schedule as s
    con.print(s.install(_cfg()))


@schedule_app.command("remove")
def schedule_remove():
    """Stop automatic searches."""
    from . import schedule as s
    con.print(s.remove())


@schedule_app.command("status")
def schedule_status():
    """Show whether automatic searches are on."""
    from . import schedule as s
    con.print(s.status(_cfg()))


def main() -> None:
    logger = logmod.setup()
    try:
        app()
    except UserError as e:
        err.print(f"[red]{e}[/red]")
        sys.exit(1)
    except KeyboardInterrupt:
        err.print("Stopped.")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        logger.error("unhandled: %s", traceback.format_exc())
        msg = getattr(e, "user_message", None) or str(e) or e.__class__.__name__
        err.print(f"[red]Something went wrong:[/red] {msg}")
        err.print(f"Details were saved to {paths.logs_dir() / 'jobapp.log'}. "
                  "Run 'jobapp report-bug' to package them for the developer.")
        sys.exit(1)
