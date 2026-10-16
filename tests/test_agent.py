import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import fixture_text
from helpers import mock_http
from jobapp import bugreport, db
from jobapp.agent import tools
from jobapp.models import JobPosting

REPO = Path(__file__).resolve().parent.parent
EXPECTED = {"find_jobs", "list_jobs", "job_details", "build_resume", "mark_job", "import_resume_prepare",
            "import_resume_submit_tex", "doctor", "update_config_filters"}


def test_mcp_server_lists_tools_via_client(profile):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "jobapp.cli_entry", "mcp"],
                                       env={**os.environ, "JOBAPP_HOME": str(profile)})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                listed = await s.list_tools()
                names = {t.name for t in listed.tools}
                lj = next(t for t in listed.tools if t.name == "list_jobs")
                res = await s.call_tool("list_jobs", {"limit": 5})
                schema = getattr(lj, "input_schema", None) or getattr(lj, "inputSchema")
                return names, schema, res
    names, schema, res = asyncio.run(asyncio.wait_for(run(), 60))
    assert EXPECTED <= names
    assert {"status", "min_match", "limit"} <= set(schema["properties"])
    payload = json.loads(res.content[0].text)
    assert payload["ok"] and payload["count"] == 0


def _seed(profile):
    conn = db.connect()
    jid, _ = db.upsert_job(conn, JobPosting("linkedin", "9", "Business Analyst", "Equinor", "Oslo",
                                            url="https://example.com/9", description="Excel and SQL"))
    return jid


def test_tool_functions(profile):
    jid = _seed(profile)
    out = tools.list_jobs()
    assert out["ok"] and out["jobs"][0]["id"] == jid
    d = tools.job_details(jid[:6])
    assert d["ok"] and d["job"]["company"] == "Equinor"
    assert not tools.job_details("zzz")["ok"]
    m = tools.mark_job(jid, "interested")
    assert m["ok"] and db.get_job(db.connect(), jid)["status"] == "interested"
    bad = tools.mark_job(jid, "bogus")
    assert not bad["ok"] and "status must be one of" in bad["error"] and "Traceback" not in bad["error"]
    doc = tools.doctor(check_sites=False)
    assert doc["ok"] and any(c["name"] == "Database" for c in doc["checks"])


def test_update_config_filters(profile):
    _seed(profile)
    r = tools.update_config_filters(title_exclude=["business"], max_age_days=10)
    assert r["ok"] and r["filters_now"]["title_exclude"] == ["business"]
    assert r["jobs_reclassified"] == 1
    assert (profile / "config.yaml.bak").exists()
    assert tools.list_jobs()["count"] == 0
    bad = tools.update_config_filters(job_types=["fultime"])
    assert not bad["ok"] and "did you mean 'fulltime'" in bad["error"]
    assert not tools.update_config_filters()["ok"]


def test_find_jobs_tool(profile, monkeypatch):
    from jobapp import poll
    real = poll.run_poll
    http = mock_http({"seeMoreJobPostings": fixture_text("linkedin", "search_page0.html")})
    monkeypatch.setattr(poll, "run_poll", lambda cfg, conn, only=None: real(cfg, conn, only=only, http=http,
                                                                            fetch_jd=False))
    tools._poll_state.update(running=False, result=None, consumed=True)
    r = tools.find_jobs(source="linkedin", wait_seconds=30)
    assert r["ok"] and r["status"] == "done"
    assert r["results"][0]["site"] == "linkedin" and r["results"][0]["found"] == 10


def test_import_tools(profile, tmp_path):
    from docx_factory import simple_resume
    from jobapp.resume import tex as texmod
    p = simple_resume(tmp_path / "r.docx")
    r = tools.import_resume_prepare(str(p))
    assert r["ok"] and "## SYSTEM" in r["prompt"]
    if texmod.detect() is None:
        pytest.skip("no LaTeX")
    correct = (Path(__file__).parent / "fixtures" / "docx_import" / "correct.tex").read_text()
    bad = tools.import_resume_submit_tex(correct.replace("12 Nordic", "twelve Nordic"))
    assert bad["ok"] and not bad["passed"] and "twelve" in bad["fix_report"]
    good = tools.import_resume_submit_tex(correct, accept_if_ok=True)
    assert good["passed"] and good["installed_as"].endswith("resume.tex")


# ── report-bug ────────────────────────────────────────────
def test_redact():
    text = ("profile:\n  name: Kari Nordmann\nemail kari.nordmann@example.no, phone +47 912 34 567, "
            "US (55" + "5) 123-" + "4567\nANTHROPIC_API_KEY=sk-ant-abc123def456ghi789\npassword: hunter2\n"
            "token gh" + "p_" + "a" * 20 + "\nposted 2026-10-15T09:00:00 version 0.1.0 run 12 of 3.14\n"
            f"path {Path.home()}/x\nKari applied at Nordmann AS")
    out = bugreport.redact(text, "Kari Nordmann")
    for leak in ("Kari", "Nordmann", "kari.nordmann@example.no", "912 34 567", "123-4567", "sk-ant-", "hunter2",
                 "gh" + "p_", str(Path.home())):
        assert leak not in out, leak
    assert "2026-10-15T09:00:00" in out and "0.1.0" in out and "3.14" in out
    assert "[REDACTED-EMAIL]" in out and "[REDACTED-PHONE]" in out and "[REDACTED-SECRET]" in out


def test_report_bug_zip(profile):
    cfg = profile / "config.yaml"
    cfg.write_text(cfg.read_text().replace("Alex Example", "Kari Nordmann"))
    (profile / ".env").write_text("GEMINI_API_KEY=AIza" + "x" * 30 + "\n")
    (profile / "logs" / "jobapp.log").write_text(
        "ERROR built resume for Kari Nordmann <kari@example.no> key=AIza" + "y" * 30 + "\n")
    from typer.testing import CliRunner
    from jobapp.cli import app
    r = CliRunner().invoke(app, ["report-bug"])
    assert r.exit_code == 0
    zips = list((profile / "output").glob("bug-report-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as z:
        names = set(z.namelist())
        assert {"system.json", "doctor.txt", "config.yaml", "logs/jobapp.log"} <= names
        assert ".env" not in names
        blob = "\n".join(z.read(n).decode() for n in names)
    for leak in ("Kari", "Nordmann", "kari@example.no", "AIza"):
        assert leak not in blob, leak


def test_mcp_config_snippet(profile):
    from typer.testing import CliRunner
    from jobapp.cli import app
    r = CliRunner().invoke(app, ["mcp-config"])
    data = json.loads(r.stdout[r.stdout.index("{"):])
    entry = data["mcpServers"]["jobapplication"]
    assert entry["args"][-1] == "mcp" and entry["env"]["JOBAPP_HOME"] == str(profile)
