"""BI Norwegian Business School student portal — login-gated (Azure B2C).

v0.1: stub. Planned design: a Playwright persistent browser profile in $JOBAPP_HOME/browser/,
the user logs in once in a visible window, later polls reuse the session cookies.
"""
from __future__ import annotations

from typing import Iterable

from ..models import JobPosting
from .base import NeedsLogin

URL = "https://portal.bi.no/en/services/vacant-positions/"
MESSAGE = ("The BI student portal needs your BI login, which JobApplication can't do yet "
           "(planned for a later version). For now, open it yourself: " + URL)


class BiPortalSource:
    name = "bi_portal"
    label = "BI student portal"
    probe_url = URL

    def fetch(self, cfg, http) -> Iterable[JobPosting]:
        raise NeedsLogin(MESSAGE)

    def fetch_description(self, job, http) -> str | None:
        return None
