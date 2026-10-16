import pytest

from jobapp import paths
from jobapp.resume.keywords import Bank, BankError
from jobapp.resume.matching import Matcher, contains, find_matched, find_missing, score, _norm

BANK = Bank.from_dict({
    "core_competencies": {"a": ["Financial Modelling", "Data Analysis", "Vision-Language Models (VLMs)",
                                 "Transformers", "Sensor Fusion"]},
    "technical_skills": {"t": ["Excel", "Power BI", "C++", "SQL", "R", "Python"], "x": ["Git"]},
    "aliases": {"financial modeling": "Financial Modelling", "powerbi": "Power BI", "dashboards": "Power BI"},
})


def c(text, kw):
    return contains(_norm(text), text, kw)


@pytest.mark.parametrize("text,kw,expected", [
    ("experience with Excel and SQL", "Excel", True),
    ("Excellent communication", "Excel", False),
    ("strong C++ skills", "C++", True),
    ("C, C# and Java", "C++", False),
    ("We use R for statistics", "R", True),
    ("R&D department", "R", True),           # acceptable: R is a token there
    ("ROS, roses", "R", False),
    ("transformer architectures", "Transformers", True),
    ("Transformers", "Transformers", True),
    ("vision language models", "Vision-Language Models (VLMs)", True),
    ("experience with VLMs", "Vision-Language Models (VLMs)", True),
    ("sensor-fusion pipelines", "Sensor Fusion", True),
    ("python3", "Python", False),
    ("Python.", "Python", True),
    ("power bi dashboards", "Power BI", True),
    ("mysql", "SQL", False),
])
def test_contains(text, kw, expected):
    assert c(text, kw) is expected


def test_aliases_and_order():
    core, tech = find_matched("Strong financial modeling. Builds dashboards in Excel.", BANK)
    assert core == ["Financial Modelling"]
    assert tech == ["Excel", "Power BI"]


def test_missing_terms():
    jd = "You know Tableau and Snowflake. Experience with Google Cloud Platform, dbt and KPI design. " \
         "Excel is a must. Join Acme Corp in Oslo."
    miss = find_missing(jd, BANK, ignore=("Acme Corp", "Oslo"))
    assert "Google Cloud Platform" in miss
    assert "KPI" in miss
    assert "Excel" not in miss
    assert not any("Acme" in m for m in miss)


def test_score_pct():
    r = score("We need Excel, SQL and Python. Tableau is nice.", BANK)
    assert r.matched == ["Excel", "SQL", "Python"]
    assert r.pct is not None and 0 < r.pct <= 100
    r2 = score(None, BANK, title="Excel Analyst")
    assert r2.pct is None and r2.matched == ["Excel"]


def test_bank_validation():
    with pytest.raises(BankError):
        Bank.from_dict({"core": []})
    with pytest.raises(BankError):
        Bank.from_dict({"core_competencies": {"a": ["X"]}, "aliases": {"y": "Z"}})
    with pytest.raises(BankError):
        Bank.from_dict({})


def test_example_bank_loads():
    b = Bank.load(paths.examples_profile() / "resume" / "keywords.yaml")
    assert "Financial Analysis" in b.core and "Excel" in b.tech


def test_matcher_saves(conn):
    from jobapp import db
    from jobapp.models import JobPosting
    jid, _ = db.upsert_job(conn, JobPosting("t", "1", "Analyst", "Acme", description="Excel and SQL daily"))
    Matcher(BANK).score_and_save(conn, db.get_job(conn, jid))
    j = db.get_job(conn, jid)
    assert j["matched"] == ["Excel", "SQL"] and j["match_pct"] > 0


def test_norwegian_jd():
    bank = Bank.load(paths.examples_profile() / "resume" / "keywords.yaml")
    core, tech = find_matched("Vi søker en kandidat med erfaring innen økonomi, analyse og Excel.", bank)
    assert "Financial Analysis" in core and "Data Analysis" in core and "Excel" in tech


def test_missing_skips_contact_people_phones_emails():
    from conftest import fixture_text
    from jobapp.sources import finn
    jd = finn.parse_ad(fixture_text("finn", "ad_contact_section.html"))["description"]
    r = score(jd, BANK, ("Eksempel Energi AS", "Oslo"))
    assert "Power BI" in r.matched and "SQL" in r.matched
    assert "Azure Synapse" in r.missing and "Google Analytics" in r.missing
    joined = " ".join(r.missing)
    for bad in ("Kari", "Nordmann", "Ola", "Testmann", "Mobil", "Forretningsutvikling"):
        assert bad not in joined, r.missing


def test_strip_contact_keeps_real_content():
    from jobapp.text import strip_contact
    jd = ("Kontakt med kunder er en sentral del av jobben, og du jobber tett med salg og marked hver dag.\n"
          "Oppstart 2024-2026.\n"
          "Contact person: Jane Example, Head of Analytics\n"
          "Phone: (555) 123-4567\n\n"
          "Requirements\n• Snowflake\n• Looker Studio\n"
          "Send questions to Jane Example.")
    out, names = strip_contact(jd)
    assert "Jane Example" in names
    assert "Kontakt med kunder" in out and "2024-2026" in out
    assert "Snowflake" in out and "Looker Studio" in out
    assert "Jane" not in out and "555" not in out
    r = score(jd, BANK)
    assert "Looker Studio" in r.missing and not any("Jane" in m for m in r.missing)
