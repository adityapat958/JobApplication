"""LinkedIn public guest endpoints — no login, no cookies."""
from __future__ import annotations

import re
from typing import Iterable, Iterator
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..http import HttpError
from ..log import get
from ..models import JobPosting
from ..text import clean, guess_job_type, html_to_text, normalize_job_type, parse_iso, parse_relative

log = get("linkedin")

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
VIEW = "https://www.linkedin.com/jobs/view/{id}"


def search_url(keywords: str, location: str, start: int, max_age_days: int | None = None) -> str:
    params = {"keywords": keywords, "location": location, "start": start}
    if max_age_days:
        params["f_TPR"] = f"r{int(max_age_days) * 86400}"
    return SEARCH + "?" + urlencode(params)


def parse_search(html: str) -> Iterator[JobPosting]:
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select("[data-entity-urn]"):
        m = re.search(r"jobPosting:(\d+)", card.get("data-entity-urn", ""))
        if not m:
            continue
        jid = m[1]
        title_el = card.select_one(".base-search-card__title")
        comp_el = card.select_one(".base-search-card__subtitle")
        loc_el = card.select_one(".job-search-card__location")
        time_el = card.select_one("time")
        title = clean(title_el.get_text() if title_el else "")
        if not title:
            continue
        posted = None
        if time_el is not None:
            posted = parse_iso(time_el.get("datetime")) or parse_relative(time_el.get_text())
        yield JobPosting(
            source="linkedin", source_id=jid, title=title,
            company=clean(comp_el.get_text() if comp_el else ""),
            location=clean(loc_el.get_text() if loc_el else ""),
            url=VIEW.format(id=jid), apply_url=VIEW.format(id=jid),
            job_type=guess_job_type(title), posted_at=posted, raw={"listed": clean(time_el.get_text()) if time_el else ""},
        )


def parse_posting(html: str) -> dict:
    """-> {description, job_type, seniority, industries}"""
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}
    d = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    if d:
        for b in d.select("button"):
            b.decompose()
        out["description"] = html_to_text(str(d)) or None
    for item in soup.select(".description__job-criteria-item"):
        h = item.select_one(".description__job-criteria-subheader")
        v = item.select_one(".description__job-criteria-text")
        if not (h and v):
            continue
        key, val = clean(h.get_text()).lower(), clean(v.get_text())
        if "employment type" in key:
            out["job_type"] = normalize_job_type(val)
            out["employment_type"] = val
        elif "seniority" in key:
            out["seniority"] = val
        elif "industr" in key:
            out["industries"] = val
    return out


class LinkedInSource:
    name = "linkedin"
    label = "LinkedIn"
    probe_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=analyst&start=0"

    def fetch(self, cfg, http) -> Iterable[JobPosting]:
        lc = cfg.sources.linkedin
        max_age = cfg.filters.max_age_days
        seen: set[str] = set()
        for s in lc.searches:
            start = 0
            for _page in range(lc.max_pages):
                url = search_url(s.keywords, s.location, start, max_age)
                r = http.get(url)
                if r.status_code in (400, 404):
                    break  # past the last page
                if r.status_code >= 400:
                    raise HttpError(f"LinkedIn answered {r.status_code}", r.status_code)
                cards = list(parse_search(r.text))
                if not cards:
                    break
                for job in cards:
                    if job.source_id not in seen:
                        seen.add(job.source_id)
                        job.raw["search"] = f"{s.keywords} @ {s.location}"
                        yield job
                start += len(cards)

    def fetch_description(self, job, http) -> str | None:
        info = self.fetch_details(job, http)
        return info.get("description")

    def fetch_details(self, job, http) -> dict:
        sid = job.get("source_id") if isinstance(job, dict) else job.source_id
        try:
            r = http.get(POSTING.format(id=sid))
        except HttpError as e:
            log.info("JD fetch failed for %s: %s", sid, e)
            return {}
        if r.status_code >= 400:
            return {}
        return parse_posting(r.text)
