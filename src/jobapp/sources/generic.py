"""Best-effort job description from any job page: JSON-LD JobPosting first, then the main text."""
from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from ..text import html_to_text


def _walk(o: Any):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def jsonld_jobposting(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except ValueError:
            continue
        for d in _walk(data):
            t = d.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                return d
    return None


def description_from_page(html: str, min_len: int = 200) -> str | None:
    jp = jsonld_jobposting(html)
    if jp and jp.get("description"):
        txt = html_to_text(jp["description"])
        if len(txt) >= 80:
            return txt
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form"]):
        tag.decompose()
    node = soup.find("main") or soup.find("article") or soup.body
    if not node:
        return None
    txt = html_to_text(str(node))
    return txt if len(txt) >= min_len else None
