"""Plain data objects shared across sources, DB, matching."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

STATUSES = ("new", "interested", "applied", "interview", "rejected", "offer", "ignored")


@dataclass
class JobPosting:
    source: str
    source_id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    apply_url: str = ""
    job_type: str = ""          # fulltime | internship | parttime | contract | temporary | ""
    posted_at: datetime | None = None
    description: str | None = None
    language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return job_id(self.source, self.source_id)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d


def job_id(source: str, source_id: str) -> str:
    return hashlib.sha1(f"{source}|{source_id}".encode()).hexdigest()[:10]
