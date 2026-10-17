"""Match a job description against the keyword bank. Ported from the old swap.py, made
alias-aware, word-boundary based, accent/hyphen tolerant."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..text import fold, strip_boilerplate, strip_contact
from .keywords import Bank

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


def _tokens(text_norm: str) -> set[str]:
    out: set[str] = set()
    for t in re.findall(r"[\w+#.&]+", text_norm):
        t = t.strip(".")
        if t:
            out.add(t)
            if t.endswith("s"):
                out.add(t[:-1])
    return out


def _known(bank: Bank) -> tuple[set[str], list[str]]:
    known = {_norm(k) for k in bank.all} | {_norm(a) for a in bank.aliases}
    for k in bank.all:
        known |= {_norm(v) for v in _variants(k)}
    return known, sorted(known, key=len, reverse=True)


def _phrase_in(phrase: str, haystacks: list[str]) -> bool:
    pat = re.compile(r"(?<![\w+#])" + re.escape(phrase) + r"(?![\w+#])")
    return any(pat.search(h) for h in haystacks)


def _form_in(form, first: str, text_norm: str, text_raw: str, toks: set[str]) -> bool:
    from .vocab import cs_pattern
    if form.case_sensitive:
        return bool(cs_pattern(form.text).search(re.sub(r"[\-–—_/]+", " ", text_raw)))
    if first and first not in toks and first.rstrip("s") not in toks and re.fullmatch(r"\w+", first):
        return False  # fast path: the first word isn't in the text at all
    return contains(text_norm, text_raw, form.text)


_COVER_CACHE: dict[tuple[int, int], tuple] = {}


def _candidates(bank: Bank, vocab) -> list[tuple]:
    """Vocabulary terms the bank doesn't already cover, with their normalised forms (cached per bank+vocab)."""
    key = (id(bank), id(vocab))
    hit = _COVER_CACHE.get(key)
    if hit and hit[0] is bank and hit[1] is vocab:
        return hit[2]
    known, known_list = _known(bank)
    out = []
    for term in vocab.terms:
        norms = [_norm(f.text) for f in term.forms]
        if any(n in known for n in norms):
            continue
        if any(not f.case_sensitive and _phrase_in(n, known_list) for f, n in zip(term.forms, norms)):
            continue  # "Object Detection" is covered by "Object Detection and Tracking"
        out.append((term, norms, [(n.split() or [""])[0] for n in norms]))
    if len(_COVER_CACHE) > 64:
        _COVER_CACHE.clear()
    _COVER_CACHE[key] = (bank, vocab, out)
    return out


def find_missing(text: str, bank: Bank, ignore: tuple[str, ...] = (), vocab=None) -> list[str]:
    """Skills-vocabulary terms the JD mentions that the keyword bank doesn't cover."""
    from .vocab import Vocab
    vocab = vocab or Vocab.load(extra=bank.extra_vocab)
    ign = {_norm(i) for i in ignore if i}
    tn = _norm(text)
    toks = _tokens(tn)
    out: list[str] = []
    for term, norms, firsts in _candidates(bank, vocab):
        if any(n in ign for n in norms):
            continue
        if any(_form_in(f, w, tn, text, toks) for f, w in zip(term.forms, firsts)):
            out.append(term.name)
    return sorted(dict.fromkeys(out), key=str.lower)


def vocab_aliases(bank: Bank, vocab) -> dict[str, str]:
    """Vocabulary aliases of terms you have (e.g. 'maskinlæring' → your 'Machine Learning')."""
    by_norm: dict[str, str] = {}
    for k in bank.all:
        for v in _variants(k):
            by_norm.setdefault(_norm(v), k)
    for a, c in bank.aliases.items():
        by_norm.setdefault(_norm(a), c)
    out: dict[str, str] = {}
    for term in vocab.terms:
        canon = next((by_norm[_norm(f.text)] for f in term.forms if _norm(f.text) in by_norm), None)
        if not canon:
            continue
        for f in term.forms:
            n = _norm(f.text)
            if not f.case_sensitive and n not in by_norm and f.text not in bank.aliases:
                out[f.text] = canon
    return out


MIN_DENOM = 6


@dataclass
class MatchResult:
    pct: float | None
    core: list[str]
    tech: list[str]
    missing: list[str]
    variant: str | None = None

    @property
    def matched(self) -> list[str]:
        return self.core + self.tech


def clean_jd(text: str) -> str:
    """The JD without contact blocks, people's names, boilerplate, URLs, e-mails and phone numbers."""
    text, _people = strip_contact(text)
    return strip_boilerplate(text)


def score(text: str | None, bank: Bank, ignore: tuple[str, ...] = (), title: str = "", vocab=None) -> MatchResult:
    from .vocab import Vocab
    vocab = vocab or Vocab.load(extra=bank.extra_vocab)
    bank = _with_vocab_aliases(bank, vocab)
    if not text:
        core, tech = find_matched(title, bank) if title else ([], [])
        return MatchResult(None, core, tech, [])
    text = clean_jd(text)
    core, tech = find_matched(text + "\n" + title, bank)
    missing = find_missing(text, bank, ignore, vocab)
    n = len(core) + len(tech)
    # A JD naming only one or two skills tells us little, so the denominator has a floor.
    denom = max(n + len(missing), MIN_DENOM)
    pct = round(100 * n / denom, 1)
    return MatchResult(pct, core, tech, missing)


_VA_CACHE: dict[tuple[int, int], tuple] = {}


def _with_vocab_aliases(bank: Bank, vocab) -> Bank:
    key = (id(bank), id(vocab))
    hit = _VA_CACHE.get(key)
    if hit and hit[0] is bank and hit[1] is vocab:
        return hit[2]
    extra = vocab_aliases(bank, vocab)
    b = Bank(bank.core, bank.tech, {**extra, **bank.aliases}, bank.extra_vocab) if extra else bank
    if len(_VA_CACHE) > 64:
        _VA_CACHE.clear()
    _VA_CACHE[key] = (bank, vocab, b)
    return b


class Matcher:
    """Scores jobs against one keyword bank, or — with resume.variants — against the bank of the variant
    each job uses (resume.variants.pick)."""

    def __init__(self, bank: Bank | None = None, vocab=None, *, cfg=None, banks: dict | None = None):
        from .vocab import Vocab
        self.cfg = cfg
        self.banks = banks or {}
        self.bank = bank if bank is not None else next(iter(self.banks.values()), None)
        self.vocab = vocab or Vocab.load(extra=self.bank.extra_vocab if self.bank else None)
        self._vocabs: dict[int, object] = {}

    @classmethod
    def from_config(cls, cfg) -> "Matcher":
        if not cfg.resume.variants:
            return cls(Bank.load(cfg.resolve(cfg.resume.keywords)))
        from .variants import resume_for
        loaded: dict = {}
        banks = {}
        for name in cfg.resume.variants:
            p = resume_for(cfg, name).keywords
            if p not in loaded:
                loaded[p] = Bank.load(p)
            banks[name] = loaded[p]
        return cls(cfg=cfg, banks=banks)

    def variant_for(self, job: dict) -> str | None:
        if not self.banks:
            return None
        from .variants import pick
        return pick(self.cfg, job)

    def bank_for(self, job: dict) -> tuple[str | None, Bank]:
        v = self.variant_for(job)
        return v, (self.banks[v] if v else self.bank)

    def _vocab(self, v: str | None, bank: Bank):
        if v is None:
            return self.vocab
        if id(bank) not in self._vocabs:  # one vocabulary per keyword bank (variants may share a bank)
            from .vocab import Vocab
            self._vocabs[id(bank)] = Vocab.load(extra=bank.extra_vocab)
        return self._vocabs[id(bank)]

    def score_job(self, job: dict) -> MatchResult:
        v, bank = self.bank_for(job)
        ignore = (job.get("company") or "", job.get("location") or "")
        r = score(job.get("description"), bank, ignore, job.get("title") or "", self._vocab(v, bank))
        r.variant = v
        return r

    def score_and_save(self, conn, job: dict) -> MatchResult:
        from .. import db
        r = self.score_job(job)
        db.set_match(conn, job["id"], r.pct, r.matched, r.missing)
        return r
