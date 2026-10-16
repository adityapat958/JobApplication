"""Pure filtering: apply_filters(job, cfg.filters) -> (keep, reason).

Matching rules (case-insensitive):
- title/company words match whole words: "lead" does not hit "leadership", "analyst" does not hit "analysts".
  End a word with * to match word starts: "robot*" hits "robotics".
  Start with * to match word endings (Norwegian compounds): "*analytiker" hits "Finansanalytiker".
- Common abbreviations are expanded first: Sr./Sr → senior, Jr → junior, Mgr → manager, Assoc. → associate.
- locations are plain substrings ("Oslo" hits "Oslo, Norway"). Empty list = everything.
- Unknown values (no location, no job type, no date, no language) are kept, never hidden.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from .text import detect_language, fold, guess_job_type, parse_iso, to_datetime

ABBREV = [
    (r"\bsr\b\.?", "senior"), (r"\bsnr\b\.?", "senior"), (r"\bjr\b\.?", "junior"),
    (r"\bmgr\b\.?", "manager"), (r"\bassoc\b\.?", "associate"), (r"\bmgmt\b\.?", "management"),
    (r"\bvp\b\.?", "vice president"),
]


def normalize(s: str | None) -> str:
    t = re.sub(r"[\u00ad\u200b\u200c\u200d\ufeff]", "", fold(s or ""))
    for pat, rep in ABBREV:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[\s/|,;:()\[\]–—-]+", " ", t)
    return f" {t.strip()} "


@lru_cache(maxsize=2048)
def _term_re(term: str) -> re.Pattern:
    t = normalize(term).strip()
    lead, star = t.startswith("*"), t.endswith("*")
    t = t.strip("*").strip()
    words = [re.escape(w) for w in t.split()]
    body = r"\s+".join(words)
    head = r"\w*" if lead else r"(?<!\w)"
    tail = r"\w*" if star else r"(?!\w)"
    return re.compile(head + body + tail)


def has_term(text: str | None, term: str) -> bool:
    if not term.strip():
        return False
    return bool(_term_re(term).search(normalize(text)))


def first_term(text: str | None, terms: list[str]) -> str | None:
    for t in terms:
        if has_term(text, t):
            return t
    return None


def _get(job: Any, key: str) -> Any:
    return job.get(key) if isinstance(job, dict) else getattr(job, key, None)


def apply_filters(job: Any, f: Any, now: datetime | None = None) -> tuple[bool, str]:
    title = _get(job, "title") or ""
    company = _get(job, "company") or ""
    location = _get(job, "location") or ""

    if f.title_include and not first_term(title, f.title_include):
        return False, f"title has none of: {', '.join(f.title_include)}"
    hit = first_term(title, f.title_exclude)
    if hit:
        return False, f"title contains '{hit}'"

    if f.companies_include and not first_term(company, f.companies_include):
        return False, f"company '{company}' not in your company list"
    hit = first_term(company, f.companies_exclude)
    if hit:
        return False, f"company '{company}' is excluded"

    if f.locations and location.strip():
        loc = fold(location)
        if not any(fold(l) in loc for l in f.locations if l.strip()):
            return False, f"location '{location}' not in: {', '.join(f.locations)}"

    if f.job_types:
        jt = _get(job, "job_type") or guess_job_type(title)
        if jt and jt not in f.job_types:
            return False, f"job type '{jt}' not in: {', '.join(f.job_types)}"

    if f.max_age_days is not None:
        posted = _get(job, "posted_at")
        posted = parse_iso(posted) if isinstance(posted, str) else to_datetime(posted)
        if posted:
            now = now or datetime.now(timezone.utc)
            age = (now - posted).total_seconds() / 86400
            if age > f.max_age_days + 0.5:
                return False, f"posted {int(age)} days ago (limit {f.max_age_days})"

    if f.languages:
        lang = _get(job, "language") or detect_language(_get(job, "description"))
        if lang and lang not in f.languages:
            return False, f"ad language '{lang}' not in: {', '.join(f.languages)}"

    return True, ""
