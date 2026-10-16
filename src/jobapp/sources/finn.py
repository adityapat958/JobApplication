"""FINN.no jobs (Norway). Respects robots.txt: never combines industry= and occupation=,
never sends abTestKey."""
from __future__ import annotations

import re
from typing import Iterable, Iterator
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup

from ..http import HttpError, RobotsBlocked
from ..models import JobPosting
from ..text import clean, fold, guess_job_type, html_to_text, normalize_job_type, parse_date, parse_iso, \
    parse_relative, to_datetime
from .generic import jsonld_jobposting

SEARCH = "https://www.finn.no/job/search"
AD = "https://www.finn.no/job/ad/{id}"
# FINN location codes we have verified; anything else is filtered locally by text.
LOCATION_CODES = {"oslo": "1.20001.20061"}


def robots_guard(url: str) -> None:
    u = urlparse(url)
    if not u.netloc.endswith("finn.no"):
        return
    q = parse_qs(u.query)
    if "abTestKey" in q:
        raise RobotsBlocked("FINN robots.txt forbids abTestKey")
    if u.path.startswith("/job") and "industry" in q and "occupation" in q:
        raise RobotsBlocked("FINN robots.txt forbids combining industry= and occupation=")


def search_url(q: str, location: str = "", page: int = 1) -> str:
    params: dict = {"q": q}
    loc = location.strip()
    code = LOCATION_CODES.get(fold(loc)) or (loc if re.fullmatch(r"[\d.]+", loc) else "")
    if code:
        params["location"] = code
    if page > 1:
        params["page"] = page
    return SEARCH + "?" + urlencode(params)


def parse_search(html: str) -> Iterator[JobPosting]:
    soup = BeautifulSoup(html, "html.parser")
    for art in soup.select("article"):
        a = art.select_one("a[href*='/job/ad/']") or art.select_one("a.job-card-link")
        if not a:
            continue
        m = re.search(r"/job/ad/(\d+)", a.get("href", "")) or re.search(r"(\d{6,})", art.get("id", ""))
        if not m:
            continue
        aid = m[1]
        title = clean(a.get_text())
        comp = art.select_one(".text-caption strong") or art.select_one("strong")
        pills = [clean(li.get_text()) for li in art.select("ul li") if not li.select_one("time")]
        t = art.select_one("time")
        posted = (parse_iso(t.get("datetime")) or parse_relative(t.get_text())) if t else None
        teaser = art.select_one("h3")
        yield JobPosting(
            source="finn", source_id=aid, title=title, company=clean(comp.get_text() if comp else ""),
            location=pills[0] if pills else "", url=AD.format(id=aid), apply_url=AD.format(id=aid),
            job_type=guess_job_type(title), posted_at=posted,
            raw={"teaser": clean(teaser.get_text()) if teaser else ""},
        )


LABELS = {"stillingstittel": "title", "arbeidsgiver": "company", "sted": "location",
          "søknadsfrist": "deadline", "frist": "deadline", "ansettelsesform": "employment",
          "stillingsfunksjon": "function", "sektor": "sector"}


def parse_ad(html: str) -> dict:
    """-> {title, company, location, deadline (date), job_type, posted_at, description}"""
    out: dict = {}
    jp = jsonld_jobposting(html)
    if jp:
        out["title"] = clean(jp.get("title"))
        org = jp.get("hiringOrganization") or {}
        out["company"] = clean(org.get("name") if isinstance(org, dict) else str(org))
        loc = jp.get("jobLocation") or {}
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
        out["location"] = clean(addr.get("addressLocality", "")) if isinstance(addr, dict) else ""
        if jp.get("validThrough"):
            out["deadline"] = parse_date(jp["validThrough"])
        et = jp.get("employmentType")
        if isinstance(et, list):
            et = et[0] if et else ""
        out["job_type"] = normalize_job_type(et)
        out["posted_at"] = parse_iso(jp.get("datePosted"))
        if jp.get("description"):
            out["description"] = html_to_text(jp["description"])
    # Label/value pairs (dt/dd, or "Label: value" lines) — fills anything JSON-LD didn't have.
    soup = BeautifulSoup(html, "html.parser")
    pairs: list[tuple[str, str]] = [(clean(dt.get_text()), clean(dt.find_next_sibling("dd").get_text()))
                                    for dt in soup.select("dt") if dt.find_next_sibling("dd")]
    lines = [l for l in soup.get_text("\n", strip=True).splitlines() if l.strip()]
    for i, l in enumerate(lines[:-1]):
        key = l.rstrip(":").strip()
        if fold(key) in LABELS:
            j = i + 1
            if lines[j].strip() == ":" and j + 1 < len(lines):
                j += 1
            pairs.append((key, lines[j]))
    for k, v in pairs:
        field = LABELS.get(fold(k).rstrip(":"))
        if not field or out.get(field):
            continue
        if field == "deadline":
            out["deadline"] = parse_date(v)
            out["deadline_text"] = v
        elif field == "employment":
            out.setdefault("job_type", normalize_job_type(v))
        else:
            out[field] = v
    if not out.get("description"):
        body = soup.select_one(".import-decoration") or soup.select_one("main")
        if body:
            out["description"] = html_to_text(str(body)) or None
    if out.get("deadline") is not None and not isinstance(out["deadline"], str):
        out["deadline"] = out["deadline"].isoformat()
    return {k: v for k, v in out.items() if v not in (None, "")}


class FinnSource:
    name = "finn"
    label = "FINN.no"
    probe_url = "https://www.finn.no/job/search?q=analytiker"

    def fetch(self, cfg, http) -> Iterable[JobPosting]:
        if robots_guard not in http.guards:
            http.guards.append(robots_guard)
        fc = cfg.sources.finn
        seen: set[str] = set()
        for s in fc.searches:
            loc_text = fold(s.location) if s.location and fold(s.location) not in LOCATION_CODES \
                and not re.fullmatch(r"[\d.]+", s.location) else ""
            for page in range(1, fc.max_pages + 1):
                html = http.get_text(search_url(s.q, s.location, page))
                jobs = list(parse_search(html))
                if not jobs:
                    break
                fresh = 0
                for job in jobs:
                    if job.source_id in seen:
                        continue
                    seen.add(job.source_id)
                    fresh += 1
                    if loc_text and loc_text not in fold(job.location):
                        continue
                    job.raw["search"] = f"{s.q} @ {s.location}" if s.location else s.q
                    yield job
                if not fresh:
                    break

    def fetch_details(self, job, http) -> dict:
        if robots_guard not in http.guards:
            http.guards.append(robots_guard)
        sid = job.get("source_id") if isinstance(job, dict) else job.source_id
        try:
            html = http.get_text(AD.format(id=sid))
        except HttpError:
            return {}
        return parse_ad(html)

    def fetch_description(self, job, http) -> str | None:
        return self.fetch_details(job, http).get("description")


__all__ = ["FinnSource", "parse_ad", "parse_search", "search_url", "robots_guard", "to_datetime"]
