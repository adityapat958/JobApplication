import time

import pytest
from fastapi.testclient import TestClient

from jobapp import db
from jobapp.models import JobPosting
from jobapp.resume import tex as texmod
from jobapp.web.server import create_app

H = {"X-JobApp": "1"}


@pytest.fixture
def client(profile):
    conn = db.connect()
    a, _ = db.upsert_job(conn, JobPosting("linkedin", "1", "Business Analyst", "Equinor", "Oslo",
                                          url="https://example.com/1", description="Excel, SQL and Tableau daily."))
    b, _ = db.upsert_job(conn, JobPosting("finn", "2", "Senior Analyst", "DNB", "Oslo", url="https://example.com/2"))
    db.set_hidden(conn, b, True, "title contains 'senior'")
    calls = []

    def fake_poll(cfg, conn):
        calls.append(1)
        class R: source, new, errors = "linkedin", 3, []
        return [R()]
    c = TestClient(create_app(poll_fn=fake_poll))
    c.ids = (a, b)
    c.poll_calls = calls
    return c


def test_index_and_jobs(client):
    r = client.get("/")
    assert r.status_code == 200 and "JobApplication" in r.text and "Build resume" in r.text
    jobs = client.get("/api/jobs").json()
    assert {j["id"] for j in jobs} == set(client.ids)
    hidden = [j for j in jobs if j["hidden"]]
    assert hidden[0]["hidden_reason"] == "title contains 'senior'"
    assert len(client.get("/api/jobs?hidden=false").json()) == 1
    assert client.get(f"/job/{client.ids[0]}").status_code == 200
    assert client.get("/api/jobs/nope").status_code == 404


def test_post_requires_header_and_local_host(client):
    a = client.ids[0]
    r = client.post(f"/api/jobs/{a}/status", json={"status": "applied"})
    assert r.status_code == 403
    r = client.get("/api/jobs", headers={"host": "evil.example"})
    assert r.status_code == 403
    r = client.post(f"/api/jobs/{a}/status", json={"status": "applied"}, headers=H)
    assert r.json() == {"ok": True, "status": "applied", "done": 1}
    r = client.post(f"/api/jobs/{a}/status", json={"status": "bogus"}, headers=H)
    assert r.status_code == 400


def test_status_unhides(client):
    b = client.ids[1]
    client.post(f"/api/jobs/{b}/status", json={"status": "interested"}, headers=H)
    j = client.get(f"/api/jobs/{b}").json()
    assert j["hidden"] == 0


def test_save_description_rescores_and_sticks(client):
    b = client.ids[1]
    r = client.post(f"/api/jobs/{b}/description", json={"description": "Power BI, Excel and forecasting"}, headers=H)
    d = r.json()
    assert d["ok"] and "Excel" in d["matched"] and d["match_pct"] > 0
    j = client.get(f"/api/jobs/{b}").json()
    assert j["jd_saved_at"] and j["description"].startswith("Power BI")
    r = client.post(f"/api/jobs/{b}/notes", json={"notes": "ask about salary"}, headers=H)
    assert client.get(f"/api/jobs/{b}").json()["notes"] == "ask about salary"


def test_refresh(client):
    assert client.post("/api/refresh", headers=H).json()["ok"]
    for _ in range(50):
        s = client.get("/api/refresh").json()
        if not s["running"]:
            break
        time.sleep(0.05)
    assert client.poll_calls == [1]
    assert "3 new" in s["summary"]


def test_pdf_404_before_build(client):
    assert client.get(f"/api/pdf/{client.ids[0]}").status_code == 404


@pytest.mark.skipif(texmod.detect() is None, reason="no LaTeX engine")
def test_build_via_http_returns_pdf(client, monkeypatch):
    revealed = []
    monkeypatch.setattr("jobapp.web.server.reveal", lambda p: revealed.append(p) or True)
    a = client.ids[0]
    r = client.post(f"/api/build/{a}", headers=H)
    d = r.json()
    assert d["ok"], d
    assert d["filename"] == "Alex_Example_Equinor_Business-Analyst.pdf"
    assert "Excel" in d["matched"]
    pdf = client.get(d["pdf_url"])
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert "attachment" in pdf.headers["content-disposition"]
    assert client.post(f"/api/reveal/{a}", headers=H).json()["ok"]
    assert revealed and revealed[0].name == d["filename"]
