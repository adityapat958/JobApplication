import json

from typer.testing import CliRunner

from conftest import fixture_text
from helpers import mock_http
from jobapp import config, db
from jobapp.poll import refilter_all, run_poll


def cfg_for(**filters):
    return config.parse({
        "sources": {"linkedin": {"enabled": True, "max_pages": 1,
                                 "searches": [{"keywords": "analyst", "location": "Oslo"}]},
                    "bi_portal": {"enabled": True}},
        "filters": {"title_include": ["analyst", "*analytiker"], "title_exclude": ["senior"], **filters},
        "connectors": {"jsonl": {"enabled": True}},
    })


def li_http(calls=None):
    return mock_http({"seeMoreJobPostings": fixture_text("linkedin", "search_page0.html"),
                      "jobPosting/4473638585": fixture_text("linkedin", "job_4473638585.html")}, calls)


def test_poll_inserts_filters_and_fetches_jd(profile):
    cfg = cfg_for()
    conn = db.connect()
    calls = []
    res = run_poll(cfg, conn, http=li_http(calls))
    li = next(r for r in res if r.source == "linkedin")
    assert li.fetched == 10 and li.new == 10
    assert 0 < li.kept < 10
    bi = next(r for r in res if r.source == "bi_portal")
    assert bi.errors and "login" in bi.errors[0].lower()
    visible = db.list_jobs(conn)
    hidden = db.list_jobs(conn, only_hidden=True)
    assert len(visible) == li.kept and len(hidden) == 10 - li.kept
    assert all(h["hidden_reason"] for h in hidden)
    dnv = db.get_job(conn, [j["id"] for j in visible if j["source_id"] == "4473638585"][0])
    assert dnv["description"] and dnv["job_type"] == "fulltime" and dnv["language"] == "en"
    assert dnv["match_pct"] is not None and "Data Analysis" in dnv["matched"]  # enrich step scored it
    # JD fetched only for kept jobs
    jd_calls = [c for c in calls if "jobPosting/" in c]
    assert len(jd_calls) == li.kept
    runs = db.last_runs(conn)
    assert {r["source"] for r in runs} == {"linkedin", "bi_portal"}
    events = (profile / "output" / "events.jsonl").read_text().splitlines()
    assert len(events) == 10 and json.loads(events[0])["event"] == "added"


def test_repoll_keeps_user_state_and_skips_known_jd(profile):
    cfg = cfg_for()
    conn = db.connect()
    run_poll(cfg, conn, http=li_http())
    j = db.list_jobs(conn)[0]
    db.set_status(conn, j["id"], "applied")
    db.set_notes(conn, j["id"], "sent")
    calls = []
    res = run_poll(cfg, conn, http=li_http(calls))
    assert res[0].new == 0
    j2 = db.get_job(conn, j["id"])
    assert j2["status"] == "applied" and j2["notes"] == "sent"
    assert not [c for c in calls if "jobPosting/4473638585" in c]  # JD already known


def test_tracked_jobs_never_hidden(profile):
    conn = db.connect()
    run_poll(cfg_for(), conn, http=li_http())
    j = db.list_jobs(conn)[0]
    db.set_status(conn, j["id"], "interested")
    stricter = cfg_for(title_exclude=["data"])
    refilter_all(conn, stricter)
    assert not db.get_job(conn, j["id"])["hidden"]


def test_refilter_after_config_change(profile):
    conn = db.connect()
    run_poll(cfg_for(), conn, http=li_http())
    before = len(db.list_jobs(conn))
    changed = refilter_all(conn, cfg_for(title_exclude=["data"]))
    assert changed >= 1 and len(db.list_jobs(conn)) < before
    refilter_all(conn, cfg_for())
    assert len(db.list_jobs(conn)) == before


def test_dry_run_saves_nothing(profile):
    res = run_poll(cfg_for(), None, dry_run=True, http=li_http())
    assert res[0].fetched == 10 and len(res[0].preview) == 10
    conn = db.connect()
    assert db.list_jobs(conn, include_hidden=True) == []


def test_source_error_is_reported_not_raised(profile):
    conn = db.connect()
    http = mock_http({"seeMoreJobPostings": (503, "")})
    http.retries = 0
    res = run_poll(cfg_for(), conn, http=http, only="linkedin")
    assert res[0].errors and "server error" in res[0].errors[0]


def test_cli_list_show_mark(profile, monkeypatch):
    from jobapp import cli
    conn = db.connect()
    run_poll(cfg_for(), conn, http=li_http())
    runner = CliRunner()
    r = runner.invoke(cli.app, ["list", "--json"])
    rows = json.loads(r.output)
    assert rows and all(not x["hidden_reason"] for x in rows)
    r = runner.invoke(cli.app, ["list", "--hidden", "--json"])
    assert json.loads(r.output)[0]["hidden_reason"] == "title contains 'senior'"
    jid = rows[0]["id"]
    r = runner.invoke(cli.app, ["show", jid])
    assert r.exit_code == 0 and rows[0]["company"] in r.output
    r = runner.invoke(cli.app, ["mark", jid, "applied"])
    assert r.exit_code == 0 and "applied" in r.output
    r = runner.invoke(cli.app, ["mark", jid, "aplied"])
    assert r.exit_code != 0
