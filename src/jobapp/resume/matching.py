"""Match a job description against the keyword bank. Ported from the old swap.py, made
alias-aware, word-boundary based, accent/hyphen tolerant."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..text import fold, strip_contact
from .keywords import Bank

STOP = {
    "The", "And", "For", "With", "Our", "You", "Your", "We", "This", "That", "Will", "Are", "Have", "Has",
    "Their", "Its", "From", "Into", "About", "Team", "Role", "Work", "Years", "Experience", "Job",
    "Description", "Requirements", "Responsibilities", "Qualifications", "Preferred", "Plus", "Company",
    "Engineer", "Engineering", "Software", "Machine", "Learning", "Computer", "Science", "Data", "Systems",
    "System", "Skills", "Strong", "Ability", "Knowledge", "Understanding", "Development", "Design",
    "What", "Who", "How", "Why", "When", "Where", "Benefits", "Apply", "Equal", "Opportunity", "Employer",
    "About Us", "As", "In", "If", "At", "To", "Of", "On", "Is", "Be", "An", "A", "All", "Or", "Not", "By",
    "Vi", "Du", "Det", "Som", "Og", "Er", "En", "Et", "Hos", "Med", "Til", "Har", "Kan", "Skal", "Om",
    "Stillingen", "Arbeidsoppgaver", "Kvalifikasjoner", "Vi Tilbyr", "Personlige", "Egenskaper",
    "Senior", "Junior", "Lead", "Manager", "Analyst", "Intern", "Internship", "New", "Grad", "Full", "Time",
    "Remote", "Hybrid", "Location", "Salary", "Pay", "Range", "Inc", "Ltd", "LLC", "AS", "ASA", "USA", "US",
    "PhD", "MS", "BS", "M.S", "B.S", "Bachelor", "Master", "Degree", "Minimum", "Basic", "Nice", "Must",
    "Bonus", "Good", "Fit", "Series", "Inc.", "Corp", "Corporation", "Group", "EOE", "EEO", "FAQ", "CEO",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "January", "February", "March", "April", "May",
    "June", "July", "August", "September", "October", "November", "December", "Summer", "Fall", "Spring",
}
GEO = {"united states", "united kingdom", "north america", "europe", "norway", "norge", "oslo", "bergen",
       "san francisco", "new york", "bay area", "los angeles", "seattle", "boston", "remote"} | {
    s.lower() for s in "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC NYC SF".split()}


def _norm(s: str) -> str:
    t = fold(s)
    t = re.sub(r"[\u00ad\u200b\u200c\u200d\ufeff]", "", t)
    t = re.sub(r"[\-–—_/]+", " ", t)
    return re.sub(r"\s+", " ", t)


def _variants(kw: str) -> list[str]:
    out = [kw]
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", kw)
    if m:
        out += [m[1], m[2]]
    return [v for v in out if v.strip()]


@lru_cache(maxsize=4096)
def _pattern(kw: str) -> tuple[re.Pattern, bool]:
    raw = kw.strip()
    case_sensitive = len(raw) <= 2 or (raw.isupper() and len(raw) <= 3 and raw.isalpha())
    n = raw if case_sensitive else _norm(raw)
    if case_sensitive:
        n = re.sub(r"[\-–—_/]+", " ", n)
    words = n.split()
    parts = []
    for i, w in enumerate(words):
        e = re.escape(w)
        if i == len(words) - 1 and len(w) > 3 and w[-1].isalpha():
            stem = w[:-1] if (w.endswith("s") and not w.endswith("ss")) else w
            e = re.escape(stem) + "s?"
        parts.append(e)
    body = r"\s+".join(parts)
    return re.compile(r"(?<![\w+#])" + body + r"(?![\w+#])"), case_sensitive


def contains(text_norm: str, text_raw: str, kw: str) -> bool:
    for v in _variants(kw):
        pat, cs = _pattern(v)
        if pat.search(re.sub(r"[\-–—_/]+", " ", text_raw) if cs else text_norm):
            return True
    return False


def find_matched(text: str, bank: Bank) -> tuple[list[str], list[str]]:
    tn = _norm(text)
    core = [k for k in bank.core if contains(tn, text, k)]
    tech = [k for k in bank.tech if k not in core and contains(tn, text, k)]
    for alias, canon in bank.aliases.items():
        if contains(tn, text, alias):
            if canon in bank.core and canon not in core:
                core.append(canon)
            elif canon in bank.tech and canon not in tech and canon not in core:
                tech.append(canon)
    return core, tech


def find_missing(text: str, bank: Bank, ignore: tuple[str, ...] = ()) -> list[str]:
    """Title-Case / ACRONYM / CamelCase terms in the JD that aren't in the bank (likely skills to consider)."""
    known = {_norm(k) for k in bank.all} | {_norm(a) for a in bank.aliases}
    for k in bank.all:
        known |= {_norm(v) for v in _variants(k)}
    known_words = {w for k in known for w in k.split()}
    ign = {_norm(i) for i in ignore if i} | {w for i in ignore if i for w in _norm(i).split()} | GEO
    cand: set[str] = set()
    for words in _cap_runs(text):
        words = [w for w in words if _norm(w) not in ign]
        while words and words[-1] in STOP:
            words.pop()
        while words and words[0] in STOP:
            words.pop(0)
        if not words or len(words) > 3:
            continue
        term = " ".join(words)
        low = _norm(term)
        if low in known or low in ign or all(w in known_words for w in low.split()):
            continue
        camel = len(words) == 1 and re.search(r"[a-z][A-Z]", words[0])
        acronym = len(words) == 1 and words[0].isupper() and 2 <= len(words[0]) <= 6
        if (len(words) >= 2 and not any(w in STOP for w in words)) or camel or acronym:
            cand.add(term)
    return sorted(cand, key=str.lower)


def _cap_runs(text: str):
    """Runs of consecutive Capitalised/ACRONYM tokens, broken by punctuation or lowercase words."""
    for line in text.splitlines():
        run: list[str] = []
        for m in re.finditer(r"[\w+#][\w+#.\-]*|[^\w\s]", line):
            tok = m.group(0)
            end_break = tok.endswith(".") and len(tok) > 1
            tok = tok.rstrip(".")
            if tok and (tok[0].isupper() or tok[0].isdigit() and run) and re.match(r"[\w+#]", tok):
                run.append(tok)
                if end_break:
                    yield run
                    run = []
            else:
                if run:
                    yield run
                run = []
        if run:
            yield run


MIN_DENOM = 6


@dataclass
class MatchResult:
    pct: float | None
    core: list[str]
    tech: list[str]
    missing: list[str]

    @property
    def matched(self) -> list[str]:
        return self.core + self.tech


def score(text: str | None, bank: Bank, ignore: tuple[str, ...] = (), title: str = "") -> MatchResult:
    if not text:
        core, tech = find_matched(title, bank) if title else ([], [])
        return MatchResult(None, core, tech, [])
    text, people = strip_contact(text)
    core, tech = find_matched(text + "\n" + title, bank)
    missing = find_missing(text, bank, ignore + tuple(people))
    n = len(core) + len(tech)
    # A JD naming only one or two skills tells us little, so the denominator has a floor.
    denom = max(n + len(missing), MIN_DENOM)
    pct = round(100 * n / denom, 1)
    return MatchResult(pct, core, tech, missing)


class Matcher:
    def __init__(self, bank: Bank):
        self.bank = bank

    @classmethod
    def from_config(cls, cfg) -> "Matcher":
        return cls(Bank.load(cfg.resolve(cfg.resume.keywords)))

    def score_job(self, job: dict) -> MatchResult:
        ignore = (job.get("company") or "", job.get("location") or "")
        return score(job.get("description"), self.bank, ignore, job.get("title") or "")

    def score_and_save(self, conn, job: dict) -> MatchResult:
        from .. import db
        r = self.score_job(job)
        db.set_match(conn, job["id"], r.pct, r.matched, r.missing)
        return r
