"""SimplifyJobs GitHub lists (README HTML tables). Ported from the old watcher script."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable, Iterator

from ..models import JobPosting
from ..text import clean, parse_relative
from .generic import description_from_page

BASE = "https://raw.githubusercontent.com/SimplifyJobs"
LISTS = {
    "summer_internships": f"{BASE}/Summer2027-Internships/dev/README.md",
    "offseason": f"{BASE}/Summer2027-Internships/dev/README-Off-Season.md",
    "new_grad": f"{BASE}/New-Grad-Positions/dev/README.md",
}
LIST_TYPE = {"summer_internships": "internship", "offseason": "internship", "new_grad": "fulltime"}

_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_HREF = re.compile(r'href="([^"]+)"')
_SECTION = re.compile(r"^##\s+(.+)$", re.M)


def _cell_text(html: str) -> str:
    html = re.sub(r"<summary>.*?</summary>", "", html, flags=re.S)
    html = re.sub(r"<\s*/?br\s*/?>", "; ", html)
    t = re.sub(r"<[^>]+>", " ", html)
    t = t.replace("&amp;", "&").replace("&nbsp;", " ")
    t = clean(t)
    return re.sub(r"\s*;\s*", "; ", t).strip("; ")


def _strip_symbols(s: str) -> str:
    """Drop emoji/pictographs (🔥 🎓 🛂 🇺🇸 …) that the lists use as badges."""
    out = "".join(ch for ch in s if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co")
                  and not 0x1F1E6 <= ord(ch) <= 0x1F1FF and ch not in "\ufe0f\u200d")
    return clean(out)


def _strip_utm(url: str) -> str:
    url = re.sub(r"([?&])(utm_[a-z]+|ref)=[^&]*", r"\1", url)
    return re.sub(r"[?&]+$", "", url.replace("?&", "?").replace("&&", "&"))


def parse_readme(content: str, list_name: str, now: datetime | None = None) -> Iterator[JobPosting]:
    now = now or datetime.now(timezone.utc)
    sections = [(m.start(), clean(re.sub(r"[^\w\s,&/-]", "", m[1]))) for m in _SECTION.finditer(content)]

    def section_at(pos: int) -> str:
        cur = ""
        for start, name in sections:
            if start > pos:
                break
            cur = name
        return cur

    for tm in _TABLE.finditer(content):
        category = section_at(tm.start())
        company = ""
        for row in _TR.findall(tm.group(1)):
            cells = _TD.findall(row)
            if len(cells) < 4:
                continue
            c0 = _cell_text(cells[0])
            if c0 in ("↳", ""):
                c0 = company
            else:
                company = c0
            title, location, app_cell = _cell_text(cells[1]), _cell_text(cells[2]), cells[3]
            age = _cell_text(cells[4]) if len(cells) > 4 else ""
            if "🔒" in app_cell or "🔒" in cells[1]:
                continue
            apply_link = simplify_link = ""
            for link in _HREF.findall(app_cell):
                if "simplify.jobs/p/" in link:
                    simplify_link = simplify_link or link
                elif "simplify.jobs/c/" in link:
                    continue
                elif not apply_link:
                    apply_link = link
            if not (apply_link or simplify_link) or not title:
                continue
            m = re.search(r"simplify\.jobs/p/([0-9a-f-]{8,})", simplify_link)
            sid = m[1] if m else hashlib.sha1(f"{company}|{title}|{location}|{apply_link}".encode()).hexdigest()[:16]
            title, c0 = _strip_symbols(title), _strip_symbols(c0)
            yield JobPosting(
                source="simplify", source_id=sid, title=title, company=c0, location=location,
                url=_strip_utm(simplify_link or apply_link), apply_url=_strip_utm(apply_link or simplify_link),
                job_type=LIST_TYPE.get(list_name, ""), posted_at=parse_relative(age, now),
                raw={"list": list_name, "category": category, "age": age},
            )


class SimplifySource:
    name = "simplify"
    label = "Simplify lists (GitHub)"
    probe_url = LISTS["new_grad"]

    def fetch(self, cfg, http) -> Iterable[JobPosting]:
        sc = cfg.sources.simplify
        seen: set[str] = set()
        for name in sc.lists:
            url = sc.urls.get(name) or LISTS.get(name)
            if not url:
                raise ValueError(f"unknown Simplify list '{name}' (known: {', '.join(LISTS)}; "
                                 "or add it under sources.simplify.urls)")
            content = http.get_text(url)
            for job in parse_readme(content, name):
                if job.source_id not in seen:
                    seen.add(job.source_id)
                    yield job

    def fetch_description(self, job, http) -> str | None:
        url = _get(job, "apply_url") or _get(job, "url")
        if not url or "simplify.jobs" in url:
            return None
        try:
            r = http.get(url)
        except Exception:  # noqa: BLE001
            return None
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return None
        return description_from_page(r.text)


def _get(job, k):
    return job.get(k) if isinstance(job, dict) else getattr(job, k, None)
