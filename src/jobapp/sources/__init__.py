"""Source registry. To add a site: write a class with name/fetch/fetch_description, add it to REGISTRY."""
from __future__ import annotations

from .base import NeedsLogin, Source, SourceError
from .bi_portal import BiPortalSource
from .finn import FinnSource
from .linkedin import LinkedInSource
from .simplify import SimplifySource

REGISTRY: dict[str, type] = {
    "simplify": SimplifySource,
    "linkedin": LinkedInSource,
    "finn": FinnSource,
    "bi_portal": BiPortalSource,
}

__all__ = ["REGISTRY", "NeedsLogin", "Source", "SourceError", "get", "enabled", "doctor_checks"]


def get(name: str) -> Source:
    try:
        return REGISTRY[name]()
    except KeyError:
        import difflib
        g = difflib.get_close_matches(name, REGISTRY, n=1)
        raise SourceError(f"Unknown job site '{name}'. Known: {', '.join(REGISTRY)}"
                          + (f" (did you mean '{g[0]}'?)" if g else "")) from None


def enabled(cfg) -> list[str]:
    return [n for n in REGISTRY if getattr(getattr(cfg.sources, n, None), "enabled", False)]


def doctor_checks(cfg, network: bool) -> list:
    from ..doctor import FAIL, INFO, OK, WARN, Check
    from ..http import Http, HttpError
    out = []
    names = enabled(cfg)
    if not names:
        return [Check("Job sites", WARN, "none switched on",
                      "Turn on at least one site under 'sources' in config.yaml (set enabled: true).")]
    http = Http(retries=0, timeout=10) if network else None
    for n in names:
        src = get(n)
        label = f"Job site: {src.label}"
        if n == "bi_portal":
            out.append(Check(label, INFO, "needs login (planned)",
                             "The BI portal needs your student login; this will come in a later version. "
                             "Set bi_portal.enabled to false to hide this."))
            continue
        if not network:
            out.append(Check(label, INFO, "not checked (offline)"))
            continue
        try:
            r = http.head(src.probe_url)
            if r.status_code in (405, 403):
                r = http.get(src.probe_url)
            if r.status_code < 400:
                out.append(Check(label, OK, f"reachable ({r.status_code})"))
            elif r.status_code == 429:
                out.append(Check(label, WARN, "site says too many requests (429)",
                                 "Wait an hour before searching again."))
            else:
                out.append(Check(label, WARN, f"answered {r.status_code}",
                                 "The site may have changed. Run 'jobapp report-bug' if searches find nothing."))
        except HttpError as e:
            out.append(Check(label, FAIL, str(e), "Check your internet connection."))
    if http:
        http.close()
    return out
