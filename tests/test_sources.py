from datetime import datetime, timezone

import httpx
import pytest

from conftest import fixture_text
from helpers import mock_http
from jobapp import config, sources
from jobapp.http import Http, HttpError, RobotsBlocked
from jobapp.sources import finn, linkedin, simplify

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


# ── simplify ──────────────────────────────────────────────
def test_simplify_parse_internships():
    jobs = list(simplify.parse_readme(fixture_text("simplify", "summer_internships.md"), "summer_internships", NOW))
    titles = [j.title for j in jobs]
    assert "Robotics Perception Intern" in titles
    assert "Machine Learning Intern" not in titles  # 🔒 closed
    rp = next(j for j in jobs if j.title == "Robotics Perception Intern")
    assert rp.company == "ExampleCo"
    assert rp.location == "Boston, MA; Pittsburgh, PA; Remote in USA"
    assert rp.apply_url == "https://jobs.example.com/apply/123"
    assert rp.source_id == "00000000-1111-2222-3333-444444444444"
    assert rp.job_type == "internship"
    assert (NOW - rp.posted_at).days == 3
    cv = next(j for j in jobs if j.title == "Computer Vision Intern")
    assert cv.company == "ExampleCo"  # ↳ inherits company
    assert (NOW - cv.posted_at).days == 30
    assert {j.raw["category"] for j in jobs} >= {"Software Engineering Internship Roles"}
    assert len({j.source_id for j in jobs}) == len(jobs)
    assert all(j.company and j.title and j.url for j in jobs)


def test_simplify_parse_new_grad():
    jobs = list(simplify.parse_readme(fixture_text("simplify", "new_grad.md"), "new_grad", NOW))
    assert len(jobs) >= 8
    assert all(j.job_type == "fulltime" for j in jobs)
    arrows = [j for j in jobs if j.raw]
    assert all("utm_source" not in j.apply_url for j in jobs)
    assert not any(j.company in ("↳", "") for j in jobs)


def test_simplify_fetch_uses_lists():
    cfg = config.parse({"sources": {"simplify": {"enabled": True, "lists": ["summer_internships", "new_grad"]}}})
    calls = []
    http = mock_http({"Summer2027-Internships": fixture_text("simplify", "summer_internships.md"),
                      "New-Grad-Positions": fixture_text("simplify", "new_grad.md")}, calls)
    jobs = list(simplify.SimplifySource().fetch(cfg, http))
    assert len(calls) == 2 and len(jobs) > 10


def test_simplify_strips_badges():
    assert simplify._strip_symbols("🔥 TikTok") == "TikTok"
    assert simplify._strip_symbols("ML Intern 🎓🇺🇸") == "ML Intern"
    assert simplify._strip_symbols("Mondelēz International") == "Mondelēz International"


def test_simplify_unknown_list():
    cfg = config.parse({"sources": {"simplify": {"enabled": True, "lists": ["nope"]}}})
    with pytest.raises(ValueError):
        list(simplify.SimplifySource().fetch(cfg, mock_http({})))


# ── linkedin ──────────────────────────────────────────────
def test_linkedin_parse_search():
    jobs = list(linkedin.parse_search(fixture_text("linkedin", "search_page0.html")))
    assert len(jobs) == 10
    j = jobs[0]
    assert j.source_id == "4473638585" and j.title == "Data Analyst" and j.company == "DNV"
    assert j.location == "Oslo, Oslo, Norway"
    assert j.url == "https://www.linkedin.com/jobs/view/4473638585"
    assert j.posted_at.date().isoformat() == "2026-10-05"


def test_linkedin_parse_posting():
    info = linkedin.parse_posting(fixture_text("linkedin", "job_4473638585.html"))
    assert info["job_type"] == "fulltime"
    assert "assurance and risk management" in info["description"]
    assert len(info["description"]) > 500


def test_linkedin_search_url():
    u = linkedin.search_url("business analyst", "Oslo, Norway", 10, 21)
    assert "keywords=business+analyst" in u and "location=Oslo%2C+Norway" in u and "start=10" in u
    assert "f_TPR=r1814400" in u


def test_linkedin_paging_and_cap():
    cfg = config.parse({"sources": {"linkedin": {"enabled": True, "max_pages": 3,
                                                 "searches": [{"keywords": "analyst", "location": "Oslo"}]}}})
    page = fixture_text("linkedin", "search_page0.html")
    calls = []
    http = mock_http({"start=0": page, "start=10": page.replace("4473638585", "1111111111"), "start=20": ""}, calls)
    jobs = list(linkedin.LinkedInSource().fetch(cfg, http))
    assert len(calls) == 3  # third page empty -> stop
    assert len(jobs) == 11  # 10 + 1 new id (others duplicate)


def test_linkedin_backoff_429():
    n = {"i": 0}
    sleeps = []

    def handler(req):
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, text="ok")
    http = Http(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    assert http.get_text("https://www.linkedin.com/x") == "ok"
    assert len([s for s in sleeps if s >= 5]) == 2


def test_linkedin_429_gives_up_friendly():
    http = Http(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
                sleep=lambda s: None, retries=1)
    with pytest.raises(HttpError) as e:
        http.get("https://www.linkedin.com/x")
    assert "too often" in str(e.value)


def test_spacing_between_requests_same_host():
    sleeps = []
    http = Http(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
                sleep=sleeps.append)
    http.get("https://a.example/1"); http.get("https://a.example/2"); http.get("https://b.example/1")
    assert len(sleeps) == 1 and 1.9 < sleeps[0] <= 2.0


def test_linkedin_jd_failure_keeps_job():
    src = linkedin.LinkedInSource()
    http = mock_http({"jobPosting": (500, "")})
    http.retries = 0
    assert src.fetch_details({"source_id": "1"}, http) == {}


# ── finn ──────────────────────────────────────────────────
def test_finn_parse_search():
    jobs = list(finn.parse_search(fixture_text("finn", "search_analyst.html")))
    assert len(jobs) == 6
    j = jobs[0]
    assert j.source_id == "478290083"
    assert j.title == "Analytiker med ansvar for resultatoppfølging og prognose"
    assert j.company == "If Forsikring (If Skadeforsikring)"
    assert j.location == "Oslo"
    assert j.posted_at.isoformat().startswith("2026-10-09")
    assert j.url == "https://www.finn.no/job/ad/478290083"


def test_finn_parse_ad_jsonld():
    info = finn.parse_ad(fixture_text("finn", "ad_478290083.html"))
    assert info["company"].startswith("If Forsikring")
    assert info["location"] == "Oslo"
    assert info["deadline"] == "2026-10-20"
    assert info["job_type"] == "fulltime"
    assert "Produkt og Pris" in info["description"]


def test_finn_parse_ad_norwegian_labels():
    info = finn.parse_ad(fixture_text("finn", "ad_labels_only.html"))
    assert info["title"] == "Trainee – økonomi og analyse"
    assert info["company"] == "Eksempel Kraft AS"
    assert info["location"] == "Bergen"
    assert info["deadline"] == "2026-10-15"
    assert info["job_type"] == "fulltime"
    assert "budsjettering" in info["description"]


def test_finn_robots_rules():
    finn.robots_guard("https://www.finn.no/job/search?q=x&industry=1")
    with pytest.raises(RobotsBlocked):
        finn.robots_guard("https://www.finn.no/job/search?q=x&industry=1&occupation=2")
    with pytest.raises(RobotsBlocked):
        finn.robots_guard("https://www.finn.no/job/search?q=x&abTestKey=a")
    assert "abTestKey" not in finn.search_url("analyst", "Oslo", 2)
    assert "location=1.20001.20061" in finn.search_url("analyst", "Oslo")
    assert "location" not in finn.search_url("analyst", "Bergen")


def test_finn_fetch_filters_location_text_and_stops():
    cfg = config.parse({"sources": {"finn": {"enabled": True, "max_pages": 3,
                                             "searches": [{"q": "analyst", "location": "Ullern"}]}}})
    page = fixture_text("finn", "search_analyst.html")
    calls = []
    http = mock_http({"page=2": page, "finn.no/job/search": page}, calls)
    jobs = list(finn.FinnSource().fetch(cfg, http))
    assert all("ullern" in j.location.lower() for j in jobs) and jobs
    assert len(calls) == 2  # page 2 had nothing new -> stop
    assert finn.robots_guard in http.guards


# ── bi portal + registry ─────────────────────────────────
def test_bi_portal_needs_login():
    with pytest.raises(sources.NeedsLogin) as e:
        list(sources.get("bi_portal").fetch(None, None))
    assert "login" in str(e.value).lower()


def test_registry():
    assert set(sources.REGISTRY) == {"simplify", "linkedin", "finn", "bi_portal"}
    with pytest.raises(sources.SourceError) as e:
        sources.get("linkdin")
    assert "linkedin" in str(e.value)
    for name in sources.REGISTRY:
        s = sources.get(name)
        assert isinstance(s, sources.Source)
