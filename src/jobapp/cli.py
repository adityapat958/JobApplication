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
resume_app = typer.Typer(no_args_is_help=True, help="Your resume: import from Word or PDF.")
schedule_app = typer.Typer(no_args_is_help=True, help="Run job searches automatically.")
app.add_typer(config_app, name="config")
app.add_typer(resume_app, name="resume")
app.add_typer(schedule_app, name="schedule")
connectors_app = typer.Typer(no_args_is_help=True, help="Send your jobs to other apps (e.g. Obsidian notes).")
coverletter_app = typer.Typer(no_args_is_help=True, help="Cover letter settings (template, style, samples).")
app.add_typer(coverletter_app, name="coverletter")
app.add_typer(connectors_app, name="connectors")

con = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)


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
    problems = config_mod.runtime_problems(cfg)
    if problems:
        con.print("[red]Your settings have a problem:[/red]")
        for p in problems:
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
                        order=sort, limit=limit, title_include=config_mod.title_include())
    vcfg = _variant_cfg()
    for r in rows:
        r["variant"] = _variant_of(vcfg, r)
    if as_json:
        print(json.dumps([{k: r[k] for k in ("id", "company", "title", "location", "source", "posted_at",
                                              "match_pct", "title_score", "status", "hidden_reason", "url",
                                              "variant")}
                          | {"also_on": [a["source"] for a in r["also_on"]]} for r in rows],
                         indent=2, ensure_ascii=False))
        return
    if not rows:
        con.print("No jobs yet." if not hidden else "No hidden jobs.")
        return
    t = Table(show_lines=False)
    cols = ["id", "company", "title", "location", "source", "posted", "match", "status"]
    if vcfg:
        cols.append("resume")
    for col in cols:
        t.add_column(col)
    if hidden:
        t.add_column("why hidden")
    for r in rows:
        posted = (r["posted_at"] or r["first_seen_at"] or "")[:10]
        match = "" if r["match_pct"] is None else f"{r['match_pct']:.0f}%"
        src = r["source"] + "".join(f" +{a['source']}" for a in r.get("also_on") or [])
        cells = [r["id"], r["company"] or "", r["title"] or "", r["location"] or "", src, posted,
                 match, r["status"]]
        if vcfg:
            cells.append(r["variant"] + ("" if r.get("variant_chosen") else "*"))
        if hidden:
            cells.append(r["hidden_reason"] or "")
        t.add_row(*cells)
    con.print(t)
    if vcfg:
        con.print("[dim]resume: * = picked automatically; change with 'jobapp build <id> --variant <name>'[/dim]")


def _variant_cfg():
    """The config if it has resume variants, else None (list/show still work without a valid config)."""
    try:
        cfg = config_mod.load()
    except Exception:  # noqa: BLE001
        return None
    return cfg if cfg.resume.variants else None


def _variant_of(cfg, job: dict) -> str | None:
    if cfg is None:
        return None
    from .resume.variants import pick
    job["variant_chosen"] = bool(job.get("variant") and job["variant"] in cfg.resume.variants)
    return pick(cfg, job)


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
    from .filters import title_score
    con.print(f"  title_score: {title_score(j.get('title'), config_mod.title_include()):g}"
              "  (how well the title fits your title_include words)")
    vcfg = _variant_cfg()
    if vcfg:
        v = _variant_of(vcfg, j)
        con.print(f"  resume: {v} ({'your choice' if j['variant_chosen'] else 'picked automatically'}; "
                  f"options: {', '.join(vcfg.resume.variants)})")
    if j.get("match_pct") is not None:
        con.print(f"  match: {j['match_pct']:.0f}%")
        con.print(f"  matched: {', '.join(j['matched']) or '-'}")
        con.print(f"  missing: {', '.join(j['missing']) or '-'}")
    for a in j.get("also_on") or []:
        con.print(f"  also on: {a['source']}  {a['url'] or ''}")
    if j.get("duplicate_of"):
        con.print(f"  same job as {j['duplicate_of']} (listed there; this copy is hidden)")
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
    j, old = db.mark(conn, j["id"], status)
    from .connectors import notify_updated
    notify_updated(_cfg(), j, {"status": [old, status]})
    con.print(f"{j['company']} — {j['title']}: [bold]{status}[/bold]")


@app.command()
def rescore():
    """Re-score every saved job against your keyword list (after you edit keywords.yaml)."""
    from .resume.rescore import rescore_all
    cfg = _cfg()
    conn = _conn()
    try:
        r = rescore_all(cfg, conn)
    except ValueError as e:
        raise UserError(str(e))
    con.print(f"Re-scored {r['jobs']} job(s); {r['changed']} changed.")


@app.command()
def build(job_id: str, reveal: bool = typer.Option(False, "--reveal", help="Show the PDF in Finder/file manager."),
          variant: Optional[str] = typer.Option(None, "--variant",
                                                help="Which resume to use for this job (saved); 'auto' = pick automatically.")):
    """Build a tailored resume PDF for one job."""
    from . import db
    from .resume.service import build_for_job
    cfg = _cfg()
    conn = _conn()
    if variant is not None:
        j = db.get_job(conn, job_id)
        if not j:
            raise UserError(f"No job with id '{job_id}'.")
        set_variant(cfg, conn, j["id"], variant)
    res = build_for_job(cfg, conn, job_id)
    con.print(f"[green]PDF ready:[/green] {res.pdf}")
    if res.variant:
        con.print(f"  resume: {res.variant}")
    con.print(f"  matched {len(res.matched)} keyword(s): {', '.join(res.matched[:12]) or '-'}")
    if res.missing:
        con.print(f"  in the ad but not in your keyword list: {', '.join(res.missing[:10])}")
    for w in res.warnings:
        con.print(f"  [yellow]![/yellow] {w}")
    if reveal:
        from .platform import reveal as rv
        rv(res.pdf)


def set_variant(cfg, conn, job_id: str, variant: str | None) -> dict:
    from .resume.service import choose_variant
    try:
        return choose_variant(cfg, conn, job_id, variant)
    except ValueError as e:
        raise UserError(str(e))


@app.command()
def migrate(from_mongo: bool = typer.Option(False, "--from-mongo", help="Import jobs from the older Mongo tracker."),
            uri: str = typer.Option("mongodb://127.0.0.1:27017", "--uri"),
            db_name: str = typer.Option("jobdesk", "--db"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported; change nothing.")):
    """Import your jobs from another tracker (read-only on the other side; safe to run again)."""
    from . import migrate_mongo as mm
    if not from_mongo:
        raise UserError("Say where to import from, e.g. 'jobapp migrate --from-mongo'.")
    cfg = _cfg()
    conn = _conn()
    try:
        docs, other = mm.load_docs(uri, db_name)
    except mm.MongoImportError as e:
        raise UserError(str(e))
    rep = mm.import_docs(cfg, conn, docs, dry_run=dry_run)
    rep.not_imported = {k: v for k, v in other.items() if v}
    for line in rep.lines():
        con.print(line)
    con.print("Contacts and messages are not imported — outreach stays in the old system.")
    if dry_run:
        con.print("[yellow]Dry run: nothing was saved.[/yellow]")


@app.command()
def serve(port: int = typer.Option(8765, "--port"),
          open_browser: bool = typer.Option(True, "--open/--no-open"),
          background: bool = typer.Option(False, "--background", "-b",
                                          help="Keep running after this window/command ends (use this from Claude)."),
          stop: bool = typer.Option(False, "--stop", help="Stop a dashboard started with --background."),
          status: bool = typer.Option(False, "--status", help="Is the dashboard running?")):
    """Open the dashboard in your browser (http://127.0.0.1:8765)."""
    from .web import daemon
    if stop:
        con.print(daemon.stop()); return
    if status:
        con.print(daemon.status()); return
    _cfg()
    if background:
        con.print(daemon.start(port=port, open_browser=open_browser)); return
    from .web.server import serve as srv
    port = daemon.free_port(port)
    srv(port=port, open_browser=open_browser)


@app.command()
def mcp():
    """Run the MCP server for Claude Desktop (stdio)."""
    from .agent.mcp_server import main as mcp_main
    mcp_main()


@app.command("mcp-config")
def mcp_config():
    """Print the snippet for Claude Desktop's claude_desktop_config.json (with your real paths)."""
    import shutil
    uv = shutil.which("uv")
    repo = paths.REPO_DIR
    if uv and (repo / "pyproject.toml").exists():
        entry = {"command": uv, "args": ["--directory", str(repo), "run", "jobapp", "mcp"]}
    else:
        entry = {"command": sys.executable, "args": ["-m", "jobapp.cli_entry", "mcp"]}
    entry["env"] = {"JOBAPP_HOME": str(paths.home())}
    print(json.dumps({"mcpServers": {"jobapplication": entry}}, indent=2))
    hint = ("~/Library/Application Support/Claude/claude_desktop_config.json" if sys.platform == "darwin"
            else "Claude Desktop → Settings → Developer → Edit Config")
    err.print(f"Paste this into {hint} (merge with any existing mcpServers), then restart Claude Desktop.")


@app.command("report-bug")
def report_bug():
    """Make a zip with logs and diagnostics (personal details removed) to send to the developer."""
    from .bugreport import make_report
    p = make_report(network=False)
    con.print(f"Bug report saved: [bold]{p}[/bold]")
    con.print("Names, emails, phone numbers and passwords were removed. You can open the zip to check.")


# ── resume import ─────────────────────────────────────────
@resume_app.command("import")
def resume_import(docx: Optional[str] = typer.Argument(None, help="Your resume: Word (.docx) or PDF."),
                  prepare: bool = typer.Option(False, "--prepare", help="Write import/prompt.md for Claude."),
                  verify: bool = typer.Option(False, "--verify", help="Check import/resume.tex against your Word/PDF file."),
                  accept: bool = typer.Option(False, "--accept", help="After a passing verify, use it as your resume."),
                  api: bool = typer.Option(False, "--api", help="Do the whole loop with an API key.")):
    """Turn a Word or PDF resume into the LaTeX template (Claude does the typing, code checks it)."""
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
        raise UserError("Give your resume file (Word or PDF), e.g.: jobapp resume import ~/Desktop/resume.pdf --prepare")
    if api:
        rep = di.run_api(docx)
        con.print(rep.summary())
        raise typer.Exit(0 if rep.ok else 1)
    p = di.prepare(docx)
    con.print(f"Prompt written: [bold]{p}[/bold]")
    con.print(f"Next: write the LaTeX to {di.candidate_path()} and run 'jobapp resume import --verify'.")


# ── cover letters ─────────────────────────────────────────
@coverletter_app.command("init")
def coverletter_init(force: bool = typer.Option(False, "--force", help="Overwrite with the example versions.")):
    """Add the cover letter template, style.yaml and samples/ folder to your profile."""
    from . import letter as lt
    created = lt.init_profile(force=force)
    con.print(f"Cover letter files in {lt.profile_dir()}: " + (", ".join(created) or "already there (nothing changed)"))
    con.print("Put your own past letters in coverletter/samples/ (optional) and check coverletter/style.yaml.")


@app.command("letter")
def letter_cmd(job_id: str,
               prepare: bool = typer.Option(False, "--prepare", help="Write letters/<id>/prompt.md for Claude."),
               verify: bool = typer.Option(False, "--verify", help="Check letters/<id>/body.md."),
               accept: bool = typer.Option(False, "--accept", help="After a passing verify, make the PDF + text."),
               api: bool = typer.Option(False, "--api", help="Do the whole loop with an API key."),
               language: Optional[str] = typer.Option(None, "--language", "-l", help="en or no (default: style.yaml)."),
               as_json: bool = typer.Option(False, "--json")):
    """Write a tailored cover letter for one job (Claude writes, code checks the facts and format)."""
    from . import db
    from . import letter as lt
    job = db.get_job(_conn(), job_id)  # a unique prefix of the id is fine
    if not job:
        raise UserError(f"No job with id '{job_id}'. See 'jobapp list'.")
    job_id = job["id"]
    if verify or accept:
        if not (accept and not verify and lt.passed(job_id)):  # already verified: don't count another round
            rep = lt.verify(job_id)
            con.print(rep.summary())
            if not rep.ok:
                con.print(f"Fix list written to [bold]{lt.fix_report_path(job_id)}[/bold]")
                raise typer.Exit(1)
        if accept:
            pdf, txt = lt.accept(_cfg(), _conn(), job_id)
            con.print(f"[green]Cover letter ready:[/green] {pdf}\n  text for application forms: {txt}")
        return
    if api:
        rep = lt.run_api(_cfg(), _conn(), job_id, language)
        con.print(rep.summary())
        if rep.ok:
            pdf, txt = lt.accept(_cfg(), _conn(), job_id)
            con.print(f"[green]Cover letter ready:[/green] {pdf}\n  text: {txt}")
        raise typer.Exit(0 if rep.ok else 1)
    if prepare:
        p = lt.prepare(_cfg(), _conn(), job_id, language)
        con.print(f"Prompt written: [bold]{p}[/bold]")
        con.print(f"Next: write the letter body to {lt.body_path(job_id)} and run 'jobapp letter {job_id} --verify'.")
        return
    st = lt.status(job_id)
    if as_json:
        print(json.dumps(st, ensure_ascii=False, indent=1)); return
    for lang, rec in st["letters"].items():
        con.print(f"[green]ready ({lang})[/green]: {rec['pdf']}")
    if st.get("draft"):
        con.print(f"draft ({st['language']}): {st['draft']}, round {st['round']} of {lt.MAX_ROUNDS}")
    if st["state"] == "none":
        con.print(f"No cover letter yet. Start with: jobapp letter {job_id} --prepare")


# ── API keys (only for automatic Word/PDF import) ─────────────
key_app = typer.Typer(no_args_is_help=True, help="Store API keys safely (Keychain on a Mac).")
app.add_typer(key_app, name="key")


@key_app.command("set")
def key_set(name: str = typer.Argument(..., help="ANTHROPIC_API_KEY or GEMINI_API_KEY")):
    """Save an API key (typed hidden) in the system keychain."""
    from . import secrets
    if name not in secrets.names():
        raise UserError(f"Unknown key name. Use one of: {', '.join(secrets.names())}")
    value = typer.prompt(f"Paste your {name}", hide_input=True).strip()
    where = secrets.set(name, value)
    con.print(f"Saved {name} in {where}.")


@key_app.command("status")
def key_status():
    """Show which API keys are available (never prints them)."""
    from . import secrets
    for n in secrets.names():
        con.print(f"{n}: {'set' if secrets.get(n) else 'not set'}")


# ── connectors ────────────────────────────────────────────
@connectors_app.command("sync")
def connectors_sync(name: str = typer.Argument(..., help="Which connector: obsidian"),
                    dry_run: bool = typer.Option(False, "--dry-run", help="Only list what would change."),
                    adopt_dashboards: bool = typer.Option(False, "--adopt-dashboards",
                                                          help="Replace existing files at the dashboard note names.")):
    """Write notes for all the jobs you already have (safe to run again: unchanged notes are left alone)."""
    from . import connectors
    if name != "obsidian":
        raise UserError("Only 'obsidian' can be synced. Example: jobapp connectors sync obsidian")
    cfg = _cfg()
    if not cfg.connectors.obsidian.enabled:
        raise UserError("The Obsidian connector is switched off. Set connectors.obsidian.enabled: true in config.yaml.")
    problems = config_mod.runtime_problems(cfg)
    if problems:
        raise UserError("\n".join(problems))
    conn = _conn()
    c = connectors.get(cfg, "obsidian")
    if not dry_run and c.two_way:
        n = connectors.pull_all(cfg, conn)
        if n:
            con.print(f"Took {n} status change(s) from your notes.")
    c.adopt_dashboards = adopt_dashboards
    try:
        res = c.sync(conn, dry_run=dry_run)
        git = c.git_commit() if (c.oc.git_push and not dry_run) else None
    except Exception as e:  # noqa: BLE001
        connectors._record_error("obsidian", "sync", e)
        raise UserError(f"Couldn't write the notes: {e}")
    verb = "would be " if dry_run else ""
    try:
        c.raise_blocked(res)
        connectors._clear_error("obsidian")
    except Exception as e:  # noqa: BLE001
        if not dry_run:
            connectors._record_error("obsidian", "dashboards", e)
        err.print(f"[yellow]![/yellow] {e}")
    for label, key in (("created", "created"), ("updated", "updated"), ("regenerated", "generated")):
        for p in res[key]:
            con.print(f"  {verb}{label}: {p.relative_to(c.vault)}")
    con.print(f"{len(res['created'])} note(s) {verb}created, {len(res['updated'])} {verb}updated, "
              f"{res['unchanged']} unchanged" + (f", {len(res['generated'])} dashboard note(s) {verb}regenerated"
                                                  if res["generated"] else "") + ".")
    if res.get("shared"):
        con.print(f"{len(res['shared'])} repost(s) share the note of the same company + title (one_note_per_title).")
    if res["imported"]:
        con.print(f"{len(res['imported'])} status(es) {'would be ' if dry_run else ''}taken over from older notes "
                  "(e.g. 'applied').")
    if git:
        con.print(f"git: {git}")


# ── schedule ──────────────────────────────────────────────
@schedule_app.command("install")
def schedule_install():
    """Search for jobs automatically at the times in config.yaml."""
    from . import schedule as s
    print(s.install(_cfg()))


@schedule_app.command("remove")
def schedule_remove():
    """Stop automatic searches."""
    from . import schedule as s
    print(s.remove())


@schedule_app.command("status")
def schedule_status():
    """Show whether automatic searches are on."""
    from . import schedule as s
    print(s.status(_cfg()))


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
