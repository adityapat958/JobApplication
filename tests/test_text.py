from datetime import date, datetime, timezone

import pytest

from jobapp.text import detect_language, guess_job_type, html_to_text, normalize_job_type, parse_date, \
    parse_relative

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("s,d", [
    ("15. oktober 2026", date(2026, 10, 15)),
    ("1. mai 2027", date(2027, 5, 1)),
    ("3. des. 2026", date(2026, 12, 3)),
    ("20.10.2026", date(2026, 10, 20)),
    ("2026-10-20", date(2026, 10, 20)),
    ("October 5, 2026", date(2026, 10, 5)),
    ("5 Oct 2026", date(2026, 10, 5)),
    ("Snarest", None),
    ("31. februar 2026", None),
    ("", None),
])
def test_parse_date(s, d):
    assert parse_date(s) == d


@pytest.mark.parametrize("s,days", [
    ("1 week ago", 7), ("3 days ago", 3), ("7 dager siden", 7), ("2 uker siden", 14),
    ("0d", 0), ("5d", 5), ("1mo", 30), ("2 months ago", 60),
])
def test_parse_relative(s, days):
    assert round((NOW - parse_relative(s, NOW)).total_seconds() / 86400) == days


def test_parse_relative_hours():
    assert (NOW - parse_relative("14 timer siden", NOW)).total_seconds() == 14 * 3600


def test_job_types():
    assert guess_job_type("Summer Intern") == "internship"
    assert guess_job_type("Sommerjobb 2027 – økonomi") == "internship"
    assert guess_job_type("Deltidsstilling butikk") == "parttime"
    assert guess_job_type("Vikariat rådgiver") == "temporary"
    assert guess_job_type("Business Analyst") == ""
    assert guess_job_type("International Analyst") == ""
    assert normalize_job_type("Full-time") == "fulltime"
    assert normalize_job_type("FULL_TIME") == "fulltime"
    assert normalize_job_type("Fast") == "fulltime"
    assert normalize_job_type("Internship") == "internship"


def test_language():
    assert detect_language("Vi søker en dyktig analytiker som har erfaring med regnskap og som trives "
                           "i et miljø hos oss") == "no"
    assert detect_language("We are looking for an analyst to join our team and work with the data") == "en"
    assert detect_language("Excel") is None


def test_html_to_text():
    t = html_to_text("<p>Hello <b>there</b></p><ul><li>One</li><li>Two</li></ul>")
    assert "Hello there" in t and "• One" in t and "• Two" in t
