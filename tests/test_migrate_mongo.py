"""`jobapp migrate --from-mongo`: old tracker documents → jobs rows (fake data only)."""
from datetime import datetime

import pytest
from typer.testing import CliRunner

from jobapp import config, db
from jobapp import migrate_mongo as mm
from jobapp.connectors import obsidian as ob
from jobapp.models import JobPosting, job_id

VAULT_JOBS = "/srv/example/Vault/Collection/Jobs"


def docs():
    return [
        {"_id": "oid1", "id": "acme-robotics-perception-engineer", "apply_url": "https://www.linkedin.com/jobs/view/4400000001",
         "company": "Acme Robotics", "jd_body": "", "location": "Boston, MA", "match_score": 12.5, "matched": ["ROS"],
         "missing": ["Brianna Example"], "needs_manual": True,
         "note_path": f"{VAULT_JOBS}/Full-Time/Acme Robotics — Perception Engineer.md", "source": "LinkedIn",
         "status": "applied", "tier": "🏆 Tier 1", "title": "Perception Engineer", "variant": "perception",
         "date_found": "2026-09-01", "type": "fulltime", "done": True, "done_at": datetime(2026, 9, 25, 9, 10)},
        {"_id": "oid2", "id": "acme-robotics-perception-engineer-2",
         "apply_url": "https://www.linkedin.com/jobs/view/perception-engineer-at-acme-robotics-4400000001",
         "company": "Acme Robotics", "jd_body": "", "location": "Boston, MA", "match_score": 0, "matched": [],
         "missing": [], "needs_manual": True, "note_path": f"{VAULT_JOBS}/Full-Time/Acme Robotics — Perception Engineer.md",
         "source": "LinkedIn", "status": "new", "tier": "", "title": "Perception Engineer", "variant": "perception",
         "date_found": "2026-09-02", "type": "fulltime"},
        {"_id": "oid3", "id": "examplesoft-ml-engineer-intern",
         "apply_url": "https://boards.example-ats.invalid/examplesoft/jobs/123?utm_source=Simplify&ref=Simplify",
         "company": "ExampleSoft", "jd_body": "We use Python, PyTorch, Kubernetes and LLM agents.",
         "jd_saved_at": datetime(2026, 9, 23, 20, 32), "location": "Remote", "match_score": 40, "matched": ["Python"],
         "missing": [], "needs_manual": False, "note_path": f"{VAULT_JOBS}/Internships/ExampleSoft — ML Engineer Intern.md",
         "source": "SimplifyJobs", "status": "new", "tier": "🔵 Tier 3", "title": "ML Engineer Intern",
         "variant": "mle", "date_found": "2026-10-01", "type": "internship",
         "first_seen": datetime(2026, 10, 1, 8, 0)},
        {"_id": "oid4", "id": "otherco-data-intern", "apply_url": "", "company": "OtherCo", "jd_body": "",
         "location": "Austin, TX", "match_score": 0, "matched": [], "missing": [], "needs_manual": False,
         "note_path": f"{VAULT_JOBS}/Internships/OtherCo — Data Intern.md", "source": "simplify_github",
         "status": "new", "tier": "🔵 Tier 3", "title": "Data Intern", "variant": "perception",
         "date_found": "2026-01-11", "type": "internship"},
        {"_id": "oid5", "id": "jr-co-staff-ml", "apply_url": "https://jobboard.example.invalid/jobs/info/abc?utm_source=1014",
         "company": "JR Co", "jd_body": "Text " * 20, "location": "", "match_score": 4.9, "matched": [], "missing": [],
         "needs_manual": False, "note_path": f"{VAULT_JOBS}/Full-Time/JR Co — Staff ML.md", "source": "Jobright",
         "status": "new", "tier": "🔵 Tier 3", "title": "Staff ML", "variant": "mle", "date_found": "2026-08-06",
         "type": "fulltime"},
        {"_id": "oid6", "id": "ge-thing", "apply_url": "https://www.linkedin.com/jobs/view/controls-engineer-at-ge-thing-4400000099",
         "company": "", "jd_body": "", "location": "", "match_score": 0, "matched": [], "missing": [],
         "needs_manual": True, "note_path": f"{VAULT_JOBS}/Full-Time/GE Thing — Controls Engineer.md", "source": "",
         "status": "", "tier": "", "title": "", "variant": "perception", "date_found": "", "type": "fulltime"},
    ]


@pytest.fixture
def cfg(profile):
    c = config.load()
    return c.model_copy(update={"resume": c.resume.model_copy(update={"variants": {}})})


def test_doc_mapping():
    r = mm.doc_to_row(docs()[0], ["perception", "mle"])
    assert r["source"] == "linkedin" and r["source_id"] == "4400000001"
    assert r["id"] == job_id("linkedin", "4400000001")  # = what a LinkedIn poll computes
    assert r["status"] == "applied" and r["done"] == 1 and r["done_at"] == "2026-09-25T09:10:00+00:00"
    assert r["first_seen_at"] == "2026-09-01T12:00:00+00:00" and r["variant"] == "perception"
    assert r["legacy_id"] == "acme-robotics-perception-engineer" and r["note_path"].endswith("Perception Engineer.md")
    assert '"tier": "🏆 Tier 1"' in r["raw"]
    s = mm.doc_to_row(docs()[2])
    assert s["source"] == "simplify" and s["source_id"] == "legacy:examplesoft-ml-engineer-intern"
    assert s["jd_saved_at"] == "2026-09-23T20:32:00+00:00" and s["description"].startswith("We use")
    assert s["legacy_url_key"] == "boards.example-ats.invalid/examplesoft/jobs/123" and s["variant"] is None
    g = mm.doc_to_row(docs()[5])
    assert g["source"] == "linkedin" and g["source_id"] == "4400000099"
    assert (g["company"], g["title"]) == ("GE Thing", "Controls Engineer") and g["status"] == "new"
    assert mm.doc_to_row(docs()[4])["source"] == "jobright"
    assert mm.map_source("Manual") == "manual" and mm.map_source("simplify_github") == "simplify"


def test_import_idempotent_and_report(cfg):
    conn = db.connect()
    rep = mm.import_docs(cfg, conn, docs())
    assert rep.inserted == 5 and rep.same_listing == 1 and rep.stable_ids == 2
    assert rep.new_status == {"new": 4, "applied": 1} and rep.done == 1 and rep.jd_hand_saved == 1
    n = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert n == 5
    before = [tuple(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id")]
    rep2 = mm.import_docs(cfg, conn, docs())
    assert rep2.inserted == 0 and rep2.already == 5 and rep2.same_listing == 1 and rep2.rescored["changed"] == 0
    assert [tuple(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id")] == before
    j = conn.execute("SELECT * FROM jobs WHERE legacy_id='examplesoft-ml-engineer-intern'").fetchone()
    assert j["match_pct"] is not None and "Kubernetes" in j["missing"] or "Python" in j["matched"]
    lines = "\n".join(rep.lines())
    assert "same listing twice" in lines and "status (old)" in lines


def test_dry_run_writes_nothing(cfg):
    conn = db.connect()
    rep = mm.import_docs(cfg, conn, docs(), dry_run=True)
    assert rep.inserted == 5
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_repoll_hits_imported_rows(cfg):
    conn = db.connect()
    mm.import_docs(cfg, conn, docs())
    # LinkedIn: same numeric id → same row
    li = JobPosting("linkedin", "4400000001", "Perception Engineer", "Acme Robotics", "Boston, MA",
                    url="https://www.linkedin.com/jobs/view/4400000001")
    jid, new = db.upsert_job(conn, li)
    assert not new and db.get_job(conn, jid)["status"] == "applied"
    # Simplify: new source_id, same apply link (tracking parameters differ) → adopted
    sp = JobPosting("simplify", "0f0f0f0f-aaaa-bbbb-cccc-121212121212", "ML Engineer Intern", "ExampleSoft", "Remote",
                    url="https://simplify.jobs/p/0f0f0f0f-aaaa-bbbb-cccc-121212121212",
                    apply_url="https://boards.example-ats.invalid/examplesoft/jobs/123")
    jid2, new2 = db.upsert_job(conn, sp)
    row = db.get_job(conn, jid2)
    assert not new2 and row["legacy_id"] == "examplesoft-ml-engineer-intern"
    assert row["source_id"] == sp.source_id and row["jd_saved_at"]  # hand-saved JD kept
    assert db.upsert_job(conn, sp) == (jid2, False)  # next poll: direct hit
    # Simplify without a link match: the only legacy row with the same company+title+location
    sp2 = JobPosting("simplify", "abc", "Data Intern", "OtherCo", "Austin, TX", apply_url="https://x.invalid/1")
    jid3, new3 = db.upsert_job(conn, sp2)
    assert not new3 and db.get_job(conn, jid3)["legacy_id"] == "otherco-data-intern"
    # …but a different location is a different job
    sp3 = JobPosting("simplify", "abd", "Data Intern", "OtherCo", "Denver, CO", apply_url="https://x.invalid/2")
    assert db.upsert_job(conn, sp3)[1] is True
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 6


def test_url_key():
    k = db.url_key
    assert k("https://www.Example.com/jobs/1/?utm_source=Simplify&ref=Simplify") == "example.com/jobs/1"
    assert k("http://example.com/a?gh_jid=5&utm_medium=x#frag") == "example.com/a?gh_jid=5"
    assert k("") is None


def test_obsidian_adopts_exact_old_note_in_copied_vault(cfg, tmp_path):
    vault = tmp_path / "copy" / "Collection"
    ft = vault / "Jobs" / "Full-Time"
    ft.mkdir(parents=True)
    old = ('---\ncompany: "Acme Robotics"\ntitle: "Perception Engineer"\nstatus: "applied"\ndate_found: 2026-09-01\n'
           'date_applied: 2026-09-25\ntags: [job, fulltime, 1]\n---\n\n# Acme\n\n- [x] Applied\n\nmy notes\n')
    (ft / "Acme Robotics — Perception Engineer.md").write_text(old)
    # a same-named note for a different job in a different folder must not be taken
    (vault / "Jobs" / "Internships").mkdir()
    ocfg = config.parse({"resume": cfg.resume.model_dump(), "connectors": {"obsidian": {
        "enabled": True, "vault": str(vault), "folder": "Jobs"}}})
    # the original vault still exists elsewhere: it must never be read or written
    orig = tmp_path / "orig" / "Collection" / "Jobs" / "Full-Time"
    orig.mkdir(parents=True)
    (orig / "Acme Robotics — Perception Engineer.md").write_text(old)
    conn = db.connect()
    ds = docs()
    for d in ds:
        d["note_path"] = d["note_path"].replace(VAULT_JOBS, str(orig.parent))
    mm.import_docs(cfg, conn, ds)
    c = ob.ObsidianConnector(ocfg)
    res = c.sync(conn, create_all=True)
    text = (ft / "Acme Robotics — Perception Engineer.md").read_text()
    applied = db.get_job(conn, job_id("linkedin", "4400000001"))
    assert ob.note_job_id(text) == applied["id"]  # the tracked job got the shared note
    assert text.startswith(old.split("---\n\n")[0]) and "my notes" in text
    # imported jobs whose old note doesn't exist get no new note; nothing else was created
    assert res["created"] == [] and len(res["updated"]) == 1
    assert sorted(p.name for p in vault.rglob("*.md")) == ["Acme Robotics — Perception Engineer.md",
                                                            "_Dashboard.md", "_New Today.md"]
    assert c.sync(conn, create_all=True)["updated"] == []
    assert (orig / "Acme Robotics — Perception Engineer.md").read_text() == old


def test_cli_migrate_from_mongo(cfg, monkeypatch):
    from jobapp.cli import app
    monkeypatch.setattr(mm, "load_docs", lambda uri, name: (docs(), {"contacts": 10, "messages": 0}))
    r = CliRunner().invoke(app, ["migrate", "--from-mongo", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "would be imported: 5" in r.output and "contacts: 10" in r.output and "not imported" in r.output
    r = CliRunner().invoke(app, ["migrate", "--from-mongo"])
    assert "imported: 5" in r.output
    r = CliRunner().invoke(app, ["migrate", "--from-mongo"])
    assert "imported: 0" in r.output and "already imported (left as they are): 5" in r.output


def test_missing_pymongo_is_friendly(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name == "pymongo":
            raise ImportError
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(mm.MongoImportError, match="jobapp\\[mongo\\]"):
        mm.load_docs("mongodb://127.0.0.1:1", "x")


def test_load_docs_with_fake_client(monkeypatch):
    import sys
    import types

    class Coll(list):
        def find(self, _q):
            return iter(self)

        def estimated_document_count(self):
            return len(self)

    class DB(dict):
        def list_collection_names(self):
            return list(self)

    class Client:
        def __init__(self, uri, **kw):
            self.dbs = {"jobdesk": DB(jobs=Coll(docs()), contacts=Coll([{}, {}]))}

        def __getitem__(self, k):
            return self.dbs[k]

        def close(self):
            pass
    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=Client))
    d, other = mm.load_docs("mongodb://fake", "jobdesk")
    assert len(d) == 6 and other == {"contacts": 2}
    with pytest.raises(mm.MongoImportError, match="No 'jobs'"):
        mm.load_docs("mongodb://fake", "jobdesk") if False else None
        Client.__init__ = lambda self, uri, **kw: setattr(self, "dbs", {"x": DB()})
        mm.load_docs("mongodb://fake", "x")


def _simp(id_, company, title, url, loc="Kent, WA", **kw):
    return {"id": id_, "apply_url": url, "company": company, "title": title, "location": loc, "jd_body": "",
            "source": "SimplifyJobs", "status": "new", "type": "internship", "date_found": "2026-08-05",
            "note_path": f"{VAULT_JOBS}/Internships/{company} — {title}.md", **kw}


def test_old_duplicates_of_one_listing_become_one_row(cfg):
    conn = db.connect()
    ds = [_simp("rocketco-software-intern-software", "RocketCo", "Software Intern - Software", "https://ats.invalid/r/1"),
          _simp("rocketco-software-intern", "RocketCo", "Software Intern", "https://ats.invalid/r/1?utm_source=Simplify"),
          _simp("gm-mapping", "↳", "AI/ML Engineer Intern - Mapping", "https://ats.invalid/gm/2", "Warren, MI"),
          _simp("general-motors-mapping", "General Motors", "AI/ML Engineer Intern - Mapping", "https://ats.invalid/gm/2", "Warren, MI"),
          # same link, different jobs (a generic careers page) → kept apart
          _simp("big-a", "BigCo", "Compiler Engineer", "https://ats.invalid/big"),
          _simp("big-b", "BigCo", "Firmware Engineer", "https://ats.invalid/big"),
          _simp("big-c", "BigCo", "Research Scientist", "https://ats.invalid/big"),
          # same link + title but another city → different jobs
          _simp("lo-1", "LoCo", "Data Intern", "https://ats.invalid/lo", "Austin, TX"),
          _simp("lo-2", "LoCo", "Data Intern", "https://ats.invalid/lo", "Denver, CO")]
    rep = mm.import_docs(cfg, conn, ds)
    assert rep.inserted == 7 and rep.same_listing == 2
    gm = conn.execute("SELECT company FROM jobs WHERE legacy_id IN ('gm-mapping', 'general-motors-mapping')").fetchall()
    assert [r[0] for r in gm] == ["General Motors"]  # "↳" filled in from the twin
    assert mm.import_docs(cfg, conn, ds).inserted == 0
    # a poll listing one of the generic-link jobs adopts the right one by title
    p = JobPosting("simplify", "u-1", "Firmware Engineer", "BigCo", "Kent, WA", apply_url="https://ats.invalid/big")
    jid, new = db.upsert_job(conn, p)
    assert not new and db.get_job(conn, jid)["legacy_id"] == "big-b"
    p2 = JobPosting("simplify", "u-2", "Software Intern", "RocketCo", "Kent, WA", apply_url="https://ats.invalid/r/1")
    assert db.upsert_job(conn, p2)[1] is False
