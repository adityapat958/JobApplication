"""Cross-source dedupe (same job on FINN + LinkedIn + ...)."""
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from jobapp import cli, db
from jobapp.db import dedupe as dd
from jobapp.models import JobPosting


def mk(source, sid, company="DNB Bank ASA", title="Data Analyst", **kw):
    return JobPosting(source=source, source_id=sid, company=company, title=title,
                      url=f"https://{source}.example/{sid}", **kw)


@pytest.mark.parametrize("a,b", [
    ("DNB Bank ASA", "DNB"), ("Equinor ASA", "Equinor"), ("Telenor Norge AS", "Telenor"),
    ("Kongsberg Gruppen ASA", "Kongsberg"), ("Acme, Inc.", "ACME"), ("Eksempel A/S", "eksempel"),
    ("Siemens GmbH", "Siemens"), ("Example Ltd", "example llc"), ("Aker BP ASA", "Aker BP"),
    ("Øst Kraft AS", "ØST KRAFT"), ("Statkraft Norway", "Statkraft"),
])
def test_company_norm_equal(a, b):
    assert dd.norm_company(a) == dd.norm_company(b)


def test_company_norm_distinct():
    assert dd.norm_company("Aker BP") != dd.norm_company("Aker Solutions")
    assert dd.norm_company("AS") == "as"  # never empty


@pytest.mark.parametrize("a,b", [
    ("Data Engineer (m/f/d)", "Data Engineer"), ("Data Engineer (w/m/d)", "data engineer"),
    ("Data-Engineer  –  Oslo", "data engineer oslo"), ("Rådgiver (m/k)", "rådgiver"),
    ("Analyst m/f/d", "Analyst"), ("Business  Analyst!", "business analyst"),
])
def test_title_norm(a, b):
    assert dd.norm_title(a) == dd.norm_title(b)


def test_finn_linkedin_same_job_linked(conn):
    a, _ = db.upsert_job(conn, mk("finn", "1", description="full JD"))
    b, new = db.upsert_job(conn, mk("linkedin", "9", company="DNB", title="Data Analyst (m/f/d)"))
    assert new
    rows = db.list_jobs(conn)
    assert [r["id"] for r in rows] == [a]
    assert rows[0]["also_on"] == [{"source": "linkedin", "url": "https://linkedin.example/9", "id": b}]
    assert db.get_job(conn, b)["duplicate_of"] == a
    c = db.counts(conn)
    assert c["total"] == 2 and c["duplicates"] == 1 and c["visible"] == 1
    # a third site joins the same group
    db.upsert_job(conn, mk("simplify", "s1", company="DNB ASA"))
    assert [x["source"] for x in db.list_jobs(conn)[0]["also_on"]] == ["linkedin", "simplify"]


def test_primary_prefers_description_then_earliest(conn):
    a, _ = db.upsert_job(conn, mk("linkedin", "1"), ts="2026-10-01T00:00:00+00:00")
    b, _ = db.upsert_job(conn, mk("finn", "2", company="DNB", description="JD"), ts="2026-10-02T00:00:00+00:00")
    assert db.get_job(conn, a)["duplicate_of"] == b  # b has the description
    c, _ = db.upsert_job(conn, mk("simplify", "3"), ts="2026-10-03T00:00:00+00:00")
    assert db.get_job(conn, c)["duplicate_of"] == b
    # without descriptions the earliest seen wins
    x, _ = db.upsert_job(conn, mk("linkedin", "7", title="Controller"), ts="2026-10-01T00:00:00+00:00")
    y, _ = db.upsert_job(conn, mk("finn", "8", title="Controller"), ts="2026-10-05T00:00:00+00:00")
    assert db.get_job(conn, y)["duplicate_of"] == x


def test_not_linked_same_source_or_far_apart_or_different(conn):
    db.upsert_job(conn, mk("finn", "1"))
    db.upsert_job(conn, mk("finn", "2"))  # same site: a repost, not a cross-source copy
    db.upsert_job(conn, mk("linkedin", "3", title="Data Analyst Intern"))
    assert len(db.list_jobs(conn)) == 3
    db.upsert_job(conn, mk("linkedin", "p1", title="Planner", posted_at="2026-01-01T00:00:00+00:00"))
    db.upsert_job(conn, mk("finn", "p2", title="Planner", posted_at="2026-03-15T00:00:00+00:00"))
    assert len([r for r in db.list_jobs(conn) if r["title"] == "Planner"]) == 2  # > 45 days apart


def test_user_state_never_touched(conn):
    a, _ = db.upsert_job(conn, mk("linkedin", "1"))
    db.set_status(conn, a, "applied")
    db.set_notes(conn, a, "called")
    b, _ = db.upsert_job(conn, mk("finn", "2", company="DNB", description="JD"))
    ja, jb = db.get_job(conn, a), db.get_job(conn, b)
    # the tracked job stays the visible one even though the new copy has a description
    assert ja["duplicate_of"] is None and jb["duplicate_of"] == a
    assert (ja["status"], ja["done"], ja["notes"]) == ("applied", 1, "called")
    assert (jb["status"], jb["done"], jb["notes"]) == ("new", 0, None)
    # two tracked copies: both stay visible
    db.set_status(conn, b, "interested")
    assert db.get_job(conn, b)["duplicate_of"] is None
    assert db.get_job(conn, b)["status"] == "interested" and db.get_job(conn, a)["status"] == "applied"


def test_filter_hidden_copy_is_not_primary(conn):
    a, _ = db.upsert_job(conn, mk("finn", "1", description="JD"))
    b, _ = db.upsert_job(conn, mk("linkedin", "2"))
    db.set_hidden(conn, a, True, "location 'Norway' not in: Oslo")
    assert db.get_job(conn, a)["duplicate_of"] == b
    assert [r["id"] for r in db.list_jobs(conn)] == [b]


def _v1_db(path):
    """A database as 0.1.0 left it (schema 1) with a FINN + LinkedIn copy of one job."""
    raw = sqlite3.connect(path)
    raw.executescript((db.MIGRATIONS / "001_init.sql").read_text() + "\nPRAGMA user_version=1;")
    ins = ("INSERT INTO jobs (id, source, source_id, company, title, first_seen_at, last_seen_at, description, "
           "status, notes, url) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    raw.execute(ins, ("li1", "linkedin", "1", "DNB", "Data Analyst", "2026-10-01T00:00:00+00:00",
                      "2026-10-01T00:00:00+00:00", None, "interested", "ask about team", "https://li/1"))
    raw.execute(ins, ("fi1", "finn", "1", "DNB Bank ASA", "Data Analyst (m/k)", "2026-10-03T00:00:00+00:00",
                      "2026-10-03T00:00:00+00:00", "JD text", "new", None, "https://finn/1"))
    raw.execute(ins, ("fi2", "finn", "2", "Other AS", "Controller", "2026-10-03T00:00:00+00:00",
                      "2026-10-03T00:00:00+00:00", None, "new", None, "https://finn/2"))
    raw.commit()
    raw.close()


def test_migration_dedupes_existing_db(tmp_path):
    p = tmp_path / "old.db"
    _v1_db(p)
    conn = db.connect(p)
    assert db.schema_version(conn) == db.latest_version() >= 2
    li, fi = db.get_job(conn, "li1"), db.get_job(conn, "fi1")
    assert fi["duplicate_of"] == "li1" and li["duplicate_of"] is None  # the tracked one stays primary
    assert (li["status"], li["notes"]) == ("interested", "ask about team")
    assert [r["id"] for r in db.list_jobs(conn, order="company")] == ["li1", "fi2"]
    assert db.get_job(conn, "li1")["also_on"][0]["url"] == "https://finn/1"


def test_cli_list_show_also_on(profile):
    conn = db.connect()
    a, _ = db.upsert_job(conn, mk("finn", "1", description="JD"))
    db.upsert_job(conn, mk("linkedin", "2", company="DNB"))
    r = CliRunner().invoke(cli.app, ["list", "--json"])
    rows = json.loads(r.output)
    assert len(rows) == 1 and rows[0]["also_on"] == ["linkedin"]
    r = CliRunner().invoke(cli.app, ["show", a])
    assert "also on: linkedin  https://linkedin.example/2" in r.output


def test_mcp_and_dashboard_hide_duplicates(profile):
    conn = db.connect()
    db.upsert_job(conn, mk("finn", "1", description="JD"))
    db.upsert_job(conn, mk("linkedin", "2", company="DNB"))
    from jobapp.agent import tools
    out = tools.list_jobs()
    assert out["count"] == 1 and out["jobs"][0]["also_on"] == ["linkedin"]
    from fastapi.testclient import TestClient
    from jobapp.web.server import create_app
    rows = TestClient(create_app()).get("/api/jobs").json()
    assert len(rows) == 1 and rows[0]["also_on"][0]["source"] == "linkedin"
