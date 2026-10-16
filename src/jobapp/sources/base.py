"""Source plugin interface."""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from ..http import Http
from ..models import JobPosting


class NeedsLogin(RuntimeError):
    """The site needs the user to log in; not supported yet."""


class SourceError(RuntimeError):
    pass


@runtime_checkable
class Source(Protocol):
    name: str
    label: str            # human name for messages
    probe_url: str        # one URL for doctor's reachability check

    def fetch(self, cfg, http: Http) -> Iterable[JobPosting]: ...
    def fetch_description(self, job: dict | JobPosting, http: Http) -> str | None: ...
