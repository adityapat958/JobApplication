"""Ranking tiebreak: match_pct desc → title_score desc → posted desc."""
import json

import yaml
from typer.testing import CliRunner

from jobapp import cli, db, paths
from jobapp.filters import GENERIC_WEIGHT, term_weight, title_score
from jobapp.models import JobPosting

INCLUDE = ["data scientist", "analyst", "graduate", "trainee", "intern*"]


def test_term_weights():
    assert term_weight("graduate") == term_weight("trainee") == term_weight("intern*") == GENERIC_WEIGHT
    assert term_weight("junior") == GENERIC_WEIGHT
    assert term_weight("data scientist") > term_weight("analyst") > GENERIC_WEIGHT
    assert term_weight("business intelligence analyst") > term_weight("data scientist")


def test_title_score():
    assert title_score("Graduate Subsea Pipelines Engineer", INCLUDE) == GENERIC_WEIGHT
    assert title_score("Data Scientist", INCLUDE) > 1
    assert title_score("Graduate Data Scientist", INCLUDE) == title_score("Data Scientist", INCLUDE)
    assert title_score("Data Analyst", INCLUDE) > title_score("Analyst", ["analyst", "trainee"]) - 0.01
    assert title_score("Welder", INCLUDE) == 0
    assert title_score("Data Scientist", []) == 0


def _add(conn, sid, title, pct, posted):
    j = JobPosting(source="linkedin", source_id=sid, title=title, company=f"Co {sid}", url=f"https://x/{sid}",
                   posted_at=posted)
    jid, _ = db.upsert_job(conn, j)
    db.set_match(conn, jid, pct, [], [])
    return jid


def _setup(profile):
    p = paths.config_path()
    data = yaml.safe_load(p.read_text())
    data["filters"]["title_include"] = INCLUDE
    p.write_text(yaml.safe_dump(data))
    conn = db.connect()
    # the generic-only title is newer, so plain "match then newest" would put it first
    _add(conn, "1", "Graduate 2027 – Subsea Pipelines Engineer", 50.0, "2026-10-14T00:00:00+00:00")
    _add(conn, "2", "Data Scientist", 50.0, "2026-10-01T00:00:00+00:00")
    _add(conn, "3", "Analyst", 50.0, "2026-10-02T00:00:00+00:00")
    _add(conn, "4", "Trainee", 60.0, "2026-09-01T00:00:00+00:00")
    _add(conn, "5", "Data Scientist", 50.0, "2026-10-05T00:00:00+00:00")
    return conn


def test_db_match_order(profile):
    conn = _setup(profile)
    rows = db.list_jobs(conn, order="match", title_include=INCLUDE)
    assert [r["source_id"] for r in rows] == ["4", "5", "2", "3", "1"]
    assert [r["source_id"] for r in db.list_jobs(conn, order="match", title_include=INCLUDE, limit=2)] == ["4", "5"]


def test_cli_list_sort_match_and_show(profile):
    _setup(profile)
    r = CliRunner().invoke(cli.app, ["list", "--sort", "match", "--json"])
    rows = json.loads(r.output)
    titles = [x["title"] for x in rows]
    assert titles.index("Data Scientist") < titles.index("Graduate 2027 – Subsea Pipelines Engineer")
    assert rows[-1]["title_score"] == GENERIC_WEIGHT
    r = CliRunner().invoke(cli.app, ["show", rows[1]["id"]])
    assert "title_score: 2.65" in r.output


def test_mcp_and_dashboard_order(profile):
    _setup(profile)
    from jobapp.agent import tools
    out = tools.list_jobs()
    assert [j["title"] for j in out["jobs"]][:2] == ["Trainee", "Data Scientist"]
    assert out["jobs"][-1]["title"].startswith("Graduate") and "title_score" in out["jobs"][0]
    from fastapi.testclient import TestClient
    from jobapp.web.server import create_app
    rows = TestClient(create_app()).get("/api/jobs").json()
    assert rows[-1]["title"].startswith("Graduate") and rows[1]["title_score"] > 1
