"""Real network checks — opt-in: pytest -m live. One or two requests per site."""
import pytest

from jobapp import config
from jobapp.http import Http
from jobapp.sources import finn, linkedin, simplify

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def http():
    h = Http()
    yield h
    h.close()


def test_simplify_live(http):
    jobs = list(simplify.parse_readme(http.get_text(simplify.LISTS["new_grad"]), "new_grad"))
    assert len(jobs) > 50


def test_linkedin_live(http):
    jobs = list(linkedin.parse_search(http.get_text(linkedin.search_url("analyst", "Oslo, Norway", 0))))
    assert len(jobs) >= 5
    info = linkedin.LinkedInSource().fetch_details(jobs[0], http)
    assert info.get("description")


def test_finn_live(http):
    http.guards.append(finn.robots_guard)
    jobs = list(finn.parse_search(http.get_text(finn.search_url("analytiker"))))
    assert len(jobs) >= 5
    info = finn.FinnSource().fetch_details(jobs[0], http)
    assert info.get("title") or info.get("description")
