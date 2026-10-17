"""Skills vocabulary: the curated list of terms that may appear in a job's `missing` list.

`missing` = vocabulary terms the ad mentions that your keyword bank doesn't cover. Nothing else
(no capitalised phrases, names, slogans) can end up there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

VOCAB_PATH = Path(__file__).with_name("skills_vocab.yaml")


@dataclass(frozen=True)
class Form:
    text: str
    case_sensitive: bool = False


@dataclass
class Term:
    name: str
    forms: list[Form] = field(default_factory=list)


def _form(s: str) -> Form:
    s = str(s).strip()
    return Form(s[1:].strip(), True) if s.startswith("=") else Form(s)


def parse_terms(data) -> list[Term]:
    """{group: {Term: [aliases]}} or {Term: [aliases]} or [Term, …] → terms."""
    out: list[Term] = []

    def add(name, aliases):
        f = _form(name)
        if not f.text:
            return
        if isinstance(aliases, str):
            aliases = [aliases]
        forms = [f] + [_form(a) for a in (aliases or []) if str(a).strip()]
        out.append(Term(f.text, forms))

    def walk(d):
        if isinstance(d, list):
            for x in d:
                if isinstance(x, dict):
                    walk(x)
                else:
                    add(x, [])
        elif isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, dict):
                    walk(v)  # a group
                else:
                    add(k, v)

    walk(data or {})
    return out


@dataclass
class Vocab:
    terms: list[Term]

    @classmethod
    def load(cls, path: Path | None = None, extra=None) -> "Vocab":
        terms = default().terms if path is None else parse_terms(yaml.safe_load(Path(path).read_text("utf-8")))
        if extra:
            have = {t.name.casefold(): t for t in terms}
            for t in parse_terms(extra):
                if t.name.casefold() in have:  # extend an existing term's aliases
                    have[t.name.casefold()].forms.extend(f for f in t.forms[1:] if f not in have[t.name.casefold()].forms)
                else:
                    terms.append(t)
                    have[t.name.casefold()] = t
        return cls(terms)


@lru_cache(maxsize=1)
def _load_default() -> tuple[Term, ...]:
    return tuple(parse_terms(yaml.safe_load(VOCAB_PATH.read_text("utf-8"))))


def default() -> Vocab:
    return Vocab([Term(t.name, list(t.forms)) for t in _load_default()])


@lru_cache(maxsize=8192)
def cs_pattern(text: str) -> re.Pattern:
    words = re.sub(r"[\-–—_/]+", " ", text).split()
    body = r"\s+".join(re.escape(w) for w in words)
    return re.compile(r"(?<![\w+#])" + body + r"(?![\w+#])")
