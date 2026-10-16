from datetime import datetime, timezone

from jobapp import db
from jobapp.models import JobPosting


def mk(**kw):
    base = dict(source="linkedin", source_id="1", title="Business Analyst", company="Acme",
                location="Oslo", url="https://example.com/1")
    base.update(kw)
    return JobPosting(**base)


def test_migrations_applied(conn):
    assert db.schema_version(conn) == db.latest_version() >= 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    # idempotent
    assert db.migrate(conn) == db.latest_version()


def test_upsert_new_then_existing(conn):
    jid, new = db.upsert_job(conn, mk())
    assert new
    jid2, new2 = db.upsert_job(conn, mk(title="Business Analyst II"))
    assert jid2 == jid and not new2
    assert db.get_job(conn, jid)["title"] == "Business Analyst II"


def test_repoll_preserves_user_fields(conn):
    jid, _ = db.upsert_job(conn, mk(description="auto jd"))
    db.set_status(conn, jid, "applied")
    db.set_notes(conn, jid, "called recruiter")
    db.set_description(conn, jid, "my pasted JD", manual=True)
    db.upsert_job(conn, mk(description="fresh auto jd", title="New title"))
    j = db.get_job(conn, jid)
    assert j["status"] == "applied" and j["done"] == 1 and j["done_at"]
    assert j["notes"] == "called recruiter"
    assert j["description"] == "my pasted JD"
    assert j["title"] == "New title"


def test_repoll_updates_auto_description(conn):
    jid, _ = db.upsert_job(conn, mk(description=None))
    db.upsert_job(conn, mk(description="now we have it"))
    assert db.get_job(conn, jid)["description"] == "now we have it"
    db.upsert_job(conn, mk(description=None))
    assert db.get_job(conn, jid)["description"] == "now we have it"


def test_unique_source_id(conn):
    db.upsert_job(conn, mk())
    db.upsert_job(conn, mk(source="finn"))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_fts_and_filters(conn):
    a, _ = db.upsert_job(conn, mk(source_id="a", company="Equinor", title="Økonomi analytiker",
                                  description="Vi søker en analytiker i Oslo"))
    b, _ = db.upsert_job(conn, mk(source_id="b", company="DNB", title="Consultant"))
    db.set_match(conn, a, 55.0, ["Excel"], ["SAP"])
    db.set_hidden(conn, b, True, "title has none of: analyst")
    assert [j["id"] for j in db.list_jobs(conn, query="equinor")] == [a]
    assert [j["id"] for j in db.list_jobs(conn, query="søker")] == [a]
    assert [j["id"] for j in db.list_jobs(conn)] == [a]
    hid = db.list_jobs(conn, only_hidden=True)
    assert hid[0]["hidden_reason"].startswith("title")
    assert db.list_jobs(conn, min_match=60) == []
    assert db.get_job(conn, a)["matched"] == ["Excel"]


def test_status_validation(conn):
    import pytest
    jid, _ = db.upsert_job(conn, mk())
    with pytest.raises(ValueError):
        db.set_status(conn, jid, "bogus")
    j = db.set_status(conn, jid, "new")
    assert j["done"] == 0 and j["done_at"] is None


def test_prefix_lookup_and_runs(conn):
    jid, _ = db.upsert_job(conn, mk(posted_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    assert db.get_job(conn, jid[:6])["id"] == jid
    r = db.start_run(conn, "linkedin")
    db.finish_run(conn, r, 10, 3, ["boom"])
    run = db.last_runs(conn)[0]
    assert run["fetched"] == 10 and run["new"] == 3 and "boom" in run["errors"]
    db.add_build(conn, jid, "/x.pdf", ["Excel"])
    assert db.last_build(conn, jid)["pdf_path"] == "/x.pdf"
