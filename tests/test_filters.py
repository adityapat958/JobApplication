from datetime import datetime, timedelta, timezone

import pytest

from jobapp.config import FiltersCfg
from jobapp.filters import apply_filters, has_term
from jobapp.models import JobPosting

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def job(title="Business Analyst", company="Acme", location="Oslo, Norway", **kw):
    return JobPosting(source="t", source_id="1", title=title, company=company, location=location, **kw)


def F(**kw):
    return FiltersCfg(**kw)


@pytest.mark.parametrize("text,term,expected", [
    ("Business Analyst", "analyst", True),
    ("Business Analysts", "analyst", False),
    ("Team Lead", "lead", True),
    ("Leadership Program", "lead", False),
    ("Sr. Analyst", "senior", True),
    ("Sr Analyst", "senior", True),
    ("SR. DATA ANALYST", "senior", True),
    ("Senior Analyst", "sr", True),
    ("Jr. Consultant", "junior", True),
    ("Økonomi\u00adanalytiker", "analytiker", False),   # soft hyphen removed -> one compound word
    ("Økonomianalytiker", "*analytiker", True),
    ("Finansanalytiker", "*analytiker", True),
    ("Analytiker", "*analytiker", True),
    ("Økonomisjef", "økonomi*", True),
    ("Økonomi og analyse", "økonomi", True),
    ("ØKONOMI", "økonomi", True),
    ("Rådgiver økonomi", "rådgiver", True),
    ("Robotics Engineer", "robot*", True),
    ("Robotics Engineer", "robot", False),
    ("Machine Learning Engineer", "machine learning", True),
    ("Machine-Learning Engineer", "machine learning", True),
    ("Co-op Student", "co-op", True),
    ("Analytiker (Trainee)", "trainee", True),
    ("Café Manager", "cafe", True),
    ("", "analyst", False),
    ("Analyst", "", False),
])
def test_has_term(text, term, expected):
    assert has_term(text, term) is expected


def test_empty_filters_keep_all():
    assert apply_filters(job(), F()) == (True, "")


def test_title_include_exclude():
    f = F(title_include=["analyst", "consultant"], title_exclude=["senior", "lead"])
    assert apply_filters(job("Business Analyst"), f)[0]
    keep, why = apply_filters(job("Software Engineer"), f)
    assert not keep and why.startswith("title has none of")
    keep, why = apply_filters(job("Sr. Business Analyst"), f)
    assert not keep and "senior" in why
    assert apply_filters(job("Analyst, Leadership Development"), f)[0]


def test_norwegian_titles():
    f = F(title_include=["analytiker", "økonomi", "konsulent"], title_exclude=["leder"])
    assert apply_filters(job("Analytiker i økonomiavdelingen"), f)[0]
    assert apply_filters(job("Økonomi-konsulent"), f)[0]
    keep, why = apply_filters(job("Leder for økonomi"), f)
    assert not keep and "leder" in why


def test_locations():
    f = F(locations=["Oslo", "Remote"])
    assert apply_filters(job(location="Oslo, Oslo, Norway"), f)[0]
    assert apply_filters(job(location="Remote in USA"), f)[0]
    keep, why = apply_filters(job(location="Bergen, Norway"), f)
    assert not keep and "Bergen" in why
    assert apply_filters(job(location=""), f)[0]  # unknown location is kept
    assert apply_filters(job(location="TROMSØ"), F(locations=["tromsø"]))[0]


def test_companies():
    f = F(companies_exclude=["Meta"])
    assert not apply_filters(job(company="Meta"), f)[0]
    assert apply_filters(job(company="Metabase"), f)[0]
    f = F(companies_include=["DNB", "Equinor"])
    assert apply_filters(job(company="DNB Bank ASA"), f)[0]
    assert not apply_filters(job(company="Telenor"), f)[0]


def test_job_types():
    f = F(job_types=["fulltime"])
    assert apply_filters(job(job_type="fulltime"), f)[0]
    keep, why = apply_filters(job(job_type="internship"), f)
    assert not keep and "internship" in why
    assert not apply_filters(job("Summer Intern - Finance"), f)[0]  # guessed from title
    assert apply_filters(job("Analyst"), f)[0]  # unknown type kept


def test_max_age():
    f = F(max_age_days=21)
    assert apply_filters(job(posted_at=NOW - timedelta(days=3)), f, now=NOW)[0]
    keep, why = apply_filters(job(posted_at=NOW - timedelta(days=40)), f, now=NOW)
    assert not keep and "40 days" in why
    assert apply_filters(job(posted_at=None), f, now=NOW)[0]
    d = {"title": "Analyst", "posted_at": "2026-10-01T00:00:00+00:00"}
    assert apply_filters(d, f, now=NOW)[0]
    assert apply_filters(job(posted_at=NOW - timedelta(days=21)), f, now=NOW)[0]


def test_languages():
    f = F(languages=["en"])
    no = "Vi søker en analytiker som har erfaring med økonomi og som vil jobbe hos oss i Oslo for kunder"
    en = "We are looking for an analyst with experience in finance who will work with our team and clients"
    assert apply_filters(job(description=en), f)[0]
    keep, why = apply_filters(job(description=no), f)
    assert not keep and "'no'" in why
    assert apply_filters(job(description=None), f)[0]
    assert apply_filters(job(description=no), F(languages=["en", "no"]))[0]
