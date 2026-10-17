"""Cover letter: gates, rendering, prepare, MCP tools, CLI end to end (fake data only)."""
import json
import re

import pytest
from typer.testing import CliRunner

from jobapp import db, letter
from jobapp.models import JobPosting
from jobapp.resume import tex as texmod

from conftest import fixture_text

HAVE_TEX = texmod.detect() is not None
JD = """Northwind Analytics is looking for a Business Analyst to join our pricing team in Oslo.
You will build financial models in Excel, analyse sales data with SQL and present findings to stakeholders.
Requirements: degree in economics or business, strong Excel and SQL, Power BI is a plus, good presentation skills.
Kontaktperson: Kari Nordmann, tlf 912 34 567, kari@northwind.example
We are an equal opportunity employer."""
GOOD = fixture_text("letter", "good_body_en.md")
GOOD_NO = fixture_text("letter", "good_body_no.md")


@pytest.fixture
def job(profile):
    conn = db.connect()
    jid, _ = db.upsert_job(conn, JobPosting("linkedin", "77", "Business Analyst", "Northwind Analytics AS", "Oslo",
                                            url="https://example.com/77", description=JD))
    return conn, jid


@pytest.fixture
def ctx(job):
    from jobapp import config
    conn, jid = job
    return letter._context(config.load(), conn, jid, None)


def _gates(body, ctx, lang="en"):
    rep = letter.verify_body(body, {**ctx, "language": lang}, letter.load_style())
    return {g.name.split(" is ")[0]: g for g in rep.gates}, rep


def test_good_body_passes_all_text_gates(ctx):
    g, rep = _gates(GOOD, ctx)
    assert rep.ok, rep.summary()


def test_norwegian_body_passes_in_norwegian_and_fails_in_english(ctx):
    g, rep = _gates(GOOD_NO, ctx, "no")
    assert rep.ok, rep.summary()
    g, rep = _gates(GOOD_NO, ctx, "en")
    assert not g["Language"].ok and "Norwegian" in g["Language"].detail
    g, _ = _gates(GOOD, ctx, "no")
    assert not g["Language"].ok


def test_invented_number_and_employer_are_flagged(ctx):
    bad = GOOD.replace("12% in avoidable", "40% in avoidable").replace(
        "At Contoso Bank", "At Contoso Bank and later at Google DeepMind")
    g, rep = _gates(bad, ctx)
    assert not g["Facts traceable to resume or ad"].ok
    assert "40%" in rep.offenders and "Google" in rep.offenders and "DeepMind" in rep.offenders
    assert "12%" not in rep.offenders and "Contoso" not in rep.offenders
    assert "40%" in rep.fix_report()


def test_invented_year_and_tool_flagged_sentence_starters_not(ctx):
    bad = GOOD + "\n\nDuring 2019 I also used Kubernetes daily."
    _, rep = _gates(bad, ctx)
    assert set(rep.offenders) == {"2019", "Kubernetes"}


def test_banned_phrase(ctx):
    g, _ = _gates("I am writing to express my interest. " + GOOD.replace("enjoy most", "am passionate about"), ctx)
    assert not g["No banned phrases"].ok
    assert "passionate" in g["No banned phrases"].detail and "I am writing to express" in g["No banned phrases"].detail


def test_too_long_and_too_short(ctx):
    g, _ = _gates(GOOD + "\n\n" + GOOD, ctx)
    assert not g["Length"].ok and "shorten" in g["Length"].detail
    g, _ = _gates(GOOD.split("\n\n")[0], ctx)
    assert not g["Length"].ok


def test_placeholders(ctx):
    g, _ = _gates(GOOD + "\n\nI admire [Company] and {{role}}. TODO", ctx)
    assert not g["No placeholders"].ok
    assert "[Company]" in g["No placeholders"].detail and "TODO" in g["No placeholders"].detail


def test_company_role_and_keywords_required(ctx):
    body = GOOD.replace("Northwind Analytics", "the firm").replace("Business Analyst", "analyst")
    g, _ = _gates(body, ctx)
    assert not g["Company and role mentioned"].ok
    plain = ("I like numbers and people. " * 30)
    g, _ = _gates(plain, ctx)
    assert not g["Uses the ad's matched keywords"].ok


def test_clean_body_strips_salutation_and_signoff():
    body, warns = letter.clean_body("```markdown\nDear Hiring Manager,\n\nPara one.\n\nPara two.\n\nKind regards,\nAlex\n```")
    assert body == "Para one.\n\nPara two." and len(warns) == 2


def test_resume_plain_and_contact(profile):
    tex = (profile / "resume" / "resume.tex").read_text()
    text = letter.resume_plain(tex)
    assert "Northwind Consulting" in text and "12%" in text and "\\" not in text
    c = letter.resume_contact(tex)
    assert "alex@example.com" in c and c.startswith("{\\small")


def test_prepare_strips_jd_contact_and_writes_prompt(job):
    from jobapp import config
    conn, jid = job
    p = letter.prepare(config.load(), conn, jid)
    t = p.read_text()
    assert p == letter.job_dir(jid) / "prompt.md"
    assert "Kari" not in t and "912 34 567" not in t and "equal opportunity" not in t
    assert "pricing team" in t and "Northwind Consulting" in t and "Excel" in t
    assert not re.search(r"\{\{[A-Z_]+\}\}", t) and "body.md" in t
    meta = json.loads((letter.job_dir(jid) / "meta.json").read_text())
    assert meta["language"] == "en" and "SQL" in meta["matched"]


def test_prepare_uses_samples_same_language_first(job):
    from jobapp import config
    conn, jid = job
    d = letter.profile_dir() / "samples"
    (d / "old_no.txt").write_text("Jeg søker herved på stillingen som analytiker. " * 10)
    (d / "old_en.md").write_text("I would like to apply for the analyst role at your company. " * 10)
    t = letter.prepare(config.load(), conn, jid, "no").read_text()
    assert t.index("old_no.txt") < t.index("old_en.md")
    assert "README" not in t.split("SAMPLE LETTERS")[1]
    assert "Søknad på stillingen som" in t and "Med vennlig hilsen" in t and "Norwegian" in t


def test_coverletter_init_for_old_profiles(jobapp_home):
    jobapp_home.mkdir(parents=True)
    created = letter.init_profile()
    assert "coverletter/template.tex" in created and "coverletter/style.yaml" in created
    assert letter.init_profile() == []
    style = letter.load_style()
    assert style["max_words"] == 350 and "passionate" in style["banned_phrases"]


def test_init_adds_example_coverletter(profile):
    assert (profile / "coverletter" / "template.tex").exists()
    assert "LETTER-BODY" in (profile / "coverletter" / "template.tex").read_text()
    assert (profile / "coverletter" / "samples").is_dir()


@pytest.mark.skipif(not HAVE_TEX, reason="no LaTeX engine")
def test_render_compiles_to_one_page(ctx, tmp_path):
    rep = letter.verify_body(GOOD, ctx, letter.load_style(), compile_dir=tmp_path)
    assert rep.ok, rep.summary()
    assert texmod.page_count(rep.pdf) == 1
    tex = (tmp_path / "letter.tex").read_text()
    assert "Alex Example" in tex and "Application for the position of Business Analyst" in tex
    assert "Dear Hiring Manager," in tex and "12\\%" in tex and "<<NAME>>" not in tex.split("\\begin{document}")[1]
    long = "\n\n".join([GOOD] * 4)
    rep = letter.verify_body(long, ctx, {**letter.load_style(), "max_words": 5000}, compile_dir=tmp_path / "l")
    assert any(g.name == "Compiles to one page" and not g.ok for g in rep.gates)


def test_mcp_tools_listed():
    from jobapp.agent import tools
    names = [f.__name__ for f in tools.ALL]
    assert "cover_letter_prepare" in names and "cover_letter_submit" in names


@pytest.mark.skipif(not HAVE_TEX, reason="no LaTeX engine")
def test_mcp_prepare_submit_loop(job):
    from jobapp.agent import tools
    conn, jid = job
    r = tools.cover_letter_prepare(jid[:6])
    assert r["ok"] and "pricing team" in r["prompt"]
    r = tools.cover_letter_submit(jid, GOOD.replace("12%", "40%"))
    assert r["ok"] and not r["passed"] and "40%" in r["fix_report"] and r["round"] == 1
    r = tools.cover_letter_submit(jid, GOOD)
    assert r["passed"] and r["pdf"].endswith("_CoverLetter.pdf")


@pytest.mark.skipif(not HAVE_TEX, reason="no LaTeX engine")
def test_cli_end_to_end(job):
    from jobapp.cli import app
    conn, jid = job
    run = CliRunner().invoke
    r = run(app, ["letter", jid, "--prepare"])
    assert r.exit_code == 0, r.output
    letter.body_path(jid).write_text("Dear Hiring Manager,\n\n" + GOOD.replace("enjoy most", "am passionate about"))
    r = run(app, ["letter", jid, "--verify"])
    assert r.exit_code == 1 and "passionate" in letter.fix_report_path(jid).read_text()
    r = run(app, ["letter", jid, "--accept"])
    assert r.exit_code == 1
    letter.body_path(jid).write_text(GOOD)
    r = run(app, ["letter", jid, "--verify"])
    assert r.exit_code == 0, r.output
    r = run(app, ["letter", jid, "--accept"])
    assert r.exit_code == 0, r.output
    pdf, txt = letter.output_paths(__import__("jobapp.config").config.load(), "Northwind Analytics AS",
                                   "Business Analyst", "en")
    assert pdf.name == "Alex_Example_Northwind-Analytics-AS_Business-Analyst_CoverLetter.pdf" and pdf.exists()
    assert txt.read_text().startswith("Dear Hiring Manager,\n\nNorthwind") and txt.read_text().rstrip().endswith("Alex Example")
    meta = json.loads((letter.job_dir(jid) / "meta.json").read_text())
    assert meta["round"] == 3  # 2 failing checks + 1 passing; the final --accept doesn't count a round
    st = letter.status(jid)
    assert st["state"] == "ready" and "en" in st["letters"]
    r = run(app, ["letter", jid, "--json"])
    assert json.loads(r.output)["state"] == "ready"


@pytest.mark.skipif(not HAVE_TEX, reason="no LaTeX engine")
def test_api_mode_with_fake_caller(job):
    from jobapp import config
    conn, jid = job
    answers = iter(["Dear Hiring Manager,\n\n" + GOOD.replace("12%", "40%"), GOOD])
    prompts = []

    def call(p):
        prompts.append(p)
        return next(answers)
    rep = letter.run_api(config.load(), conn, jid, call=call)
    assert rep.ok and rep.round == 2 and "40%" in prompts[1] and "Your previous body" in prompts[1]


def test_web_letter_endpoints(job):
    from fastapi.testclient import TestClient

    from jobapp.web.server import create_app
    conn, jid = job
    c = TestClient(create_app())
    assert c.get(f"/api/letter/{jid}").json()["state"] == "none"
    r = c.post(f"/api/letter/{jid}/prepare", json={"language": "no"}, headers={"X-JobApp": "1"})
    assert r.json()["ok"] and r.json()["ask_claude"] == f"/cover-letter {jid} no"
    assert c.get(f"/api/letter/{jid}").json()["state"] == "needs_claude"
    assert c.get(f"/api/letter/{jid}/pdf").status_code == 404
    assert "Cover letter ✉" in c.get(f"/job/{jid}").text


def test_obsidian_cover_letter_key():
    from jobapp.connectors import obsidian as ob
    job = {"id": "abc", "status": "new", "company": "X", "title": "Y"}
    note = ob.render_note(job)
    assert "cover_letter" not in note
    updated = ob.update_note(note, {**job, "cover_letter": "/out/A_CoverLetter.pdf"})
    assert 'cover_letter: "/out/A_CoverLetter.pdf"' in updated or "cover_letter: /out/A_CoverLetter.pdf" in updated
    assert ob.update_note(updated, job) == updated  # later updates without the key leave it alone


def test_numbers_with_separators_and_plus(ctx):
    resume = ctx["resume"] + "\nScored 700+ leads in a CRM of 2,300 companies."
    c = {**ctx, "resume": resume}
    assert letter.fact_trace("I scored 700+ leads across 2,300 companies.", [c["resume"]], set()) == []
    assert letter.fact_trace("I scored 900+ leads across 2,400 companies.", [c["resume"]], set()) == ["900", "2,400"]


def test_norwegian_genitive_and_sentence_start_nouns():
    src = ["Research assistant at BI Norwegian Business School."]
    assert letter.fact_trace("Jeg jobber i BIs prosjekt. Fagene var gode.", src, set(), "no") == []
    assert letter.fact_trace("Fagene var gode.", src, set(), "en") == ["Fagene"]
    assert letter.fact_trace("Equinor er spennende.", src, set(), "no") == ["Equinor"]


def test_norwegian_number_style():
    src = ["Migrated a CRM of 2,300 companies and cut cost by 12%."]
    assert letter.fact_trace("Et CRM med 2 300 selskaper og 12 % lavere kostnad.", src, set(), "no") == []
    assert letter.fact_trace("Et CRM med 2 400 selskaper og 15 % lavere kostnad.", src, set(), "no") == ["2 400", "15 %"]
