"""Resume variants: several resumes (e.g. "perception" and "mle"); each job uses one of them.

variant = the user's choice for that job (jobs.variant) → else the variant whose `prefer_if` words best fit the
job title (then the job description) → else `default_variant`. Without `resume.variants` there is a single
resume (`resume.tex` / `resume.keywords`) and variant is None everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Resume:
    name: str | None
    tex: Path
    keywords: Path


def names(cfg) -> list[str]:
    return list(cfg.resume.variants)


def resume_for(cfg, name: str | None) -> Resume:
    v = cfg.resume.variants
    if not v:
        return Resume(None, cfg.resolve(cfg.resume.tex), cfg.resolve(cfg.resume.keywords))
    if name not in v:
        raise KeyError(name)
    return Resume(name, cfg.resolve(v[name].tex), cfg.resolve(v[name].keywords))


def _hits(text: str | None, terms: list[str]) -> int:
    from ..filters import _term_re, normalize
    if not text:
        return 0
    t = normalize(text)
    return sum(len(_term_re(x).findall(t)) for x in terms if x.strip())


def auto_pick(cfg, job: dict) -> str | None:
    v = cfg.resume.variants
    if not v:
        return None
    default = cfg.resume.default_variant
    title = job.get("title") or ""
    desc = job.get("description") or ""
    best, best_key = default, (0, 0)
    for name, vc in v.items():
        key = (sum(1 for x in vc.prefer_if if _hits(title, [x])), _hits(desc, vc.prefer_if))
        if key > best_key or (key == best_key and key != (0, 0) and name == default):
            best, best_key = name, key
    return best


def pick(cfg, job: dict) -> str | None:
    """The variant used for this job (user's choice first)."""
    v = cfg.resume.variants
    if not v:
        return None
    chosen = job.get("variant")
    if chosen and chosen in v:
        return chosen
    return auto_pick(cfg, job)


def validate_choice(cfg, name: str | None) -> str | None:
    """'auto'/''/None → None (automatic); otherwise must be a configured variant."""
    if name in (None, "", "auto"):
        return None
    v = names(cfg)
    if not v:
        raise ValueError("You have only one resume (no resume.variants in config.yaml).")
    if name not in v:
        import difflib
        g = difflib.get_close_matches(name, v, n=1)
        raise ValueError(f"'{name}' isn't one of your resumes ({', '.join(v)})"
                         + (f" — did you mean '{g[0]}'?" if g else ""))
    return name
