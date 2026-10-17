"""Tailored cover letter per job. The LLM writes the body; this module guarantees honesty and format.

Profile files:  coverletter/template.tex, coverletter/style.yaml, coverletter/samples/*
Work folder:    letters/<job id>/  meta.json, prompt.md, resume.txt, jd.txt, body.md (written by the agent),
                fix_report.md, build/letter.pdf
Index:          letters/index.json  {job id: {language: {pdf, txt, rounds, accepted_at}}}
Accepted:       output/<First>_<Last>_<Company>_<Role>_CoverLetter[_NO].pdf + .txt
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import db, paths
from .log import get
from .text import detect_language, fold, strip_contact

log = get("letter")
MAX_ROUNDS = 3
BODY_START, BODY_END = "% <<LETTER-BODY>>", "% <<LETTER-BODY-END>>"
LANG_NAMES = {"en": "English", "no": "Norwegian (bokmål)"}
DEFAULT_STYLE = {
    "language": "en", "tone": "warm, direct and specific; plain words; no clichés", "max_words": 350,
    "min_words": 150,
    "salutation": {"en": "Dear Hiring Manager,", "no": "Hei,"},
    "sign_off": {"en": "Kind regards,", "no": "Med vennlig hilsen"},
    "subject": {"en": "Application for the position of {role}", "no": "Søknad på stillingen som {role}"},
    "banned_phrases": ["I am writing to express", "passionate", "leverage", "synergy", "dynamic", "fast-paced"],
    "allow": [],
}
MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                 "October", "November", "December"],
          "no": ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober",
                 "november", "desember"]}
_ALLOW = set("""
i i'm i've i'd i'll dear hiring manager team hei kjære hello hi regards kind best sincerely thank thanks
monday tuesday wednesday thursday friday saturday sunday mandag tirsdag onsdag torsdag fredag lørdag søndag
english norwegian norsk engelsk bokmål nynorsk swedish svensk danish dansk german tysk french fransk spanish
spansk italian hindi chinese mandarin japanese arabic portuguese dutch finnish polish russian
""".split()) | {m.lower() for ms in MONTHS.values() for m in ms} | {m[:3].lower() for m in MONTHS["en"]}
# Capitalised only because they start a sentence: fine even if the resume/ad doesn't contain them.
_STARTERS = set("""
a an the i my me mine in at on of to for from with without by as and but or so yet if when while since
during after before through over under across within between beyond until because although though however
this that these those there here it its it's what why how who which where whether both each every all any
most more many much some such also again still then thus therefore together finally first second third
next last recently currently previously today now later earlier already alongside outside inside working
building having being leading using applying joining combining bringing learning helping supporting given
having looking reading seeing your you you're we we're our ours their they he she his her one two three
yes no not never only just even moreover furthermore additionally beyond above below besides instead
whatever whenever wherever overall ultimately importantly equally similarly likewise meanwhile
jeg meg min mitt mine vi oss vår vårt våre dere du deg din ditt det den de dette disse der her som hvor
hva hvorfor hvordan når hvis mens fordi siden etter før under gjennom over med uten ved hos for til fra
på av om og men eller så også både enten først deretter til slutt nå samtidig dessuten derfor likevel
spesielt særlig gjerne takk ikke bare en et ett noen mange flere mest alle hver hele slik sammen
""".split())
_BOILER = re.compile(
    r"(equal opportunity|eeo\b|affirmative action|regardless of (race|gender)|reasonable accommodation|"
    r"we (do not|don't) accept (unsolicited|agency)|privacy (policy|notice)|cookie|personvern|"
    r"offentleglova|offentlighetsloven|søkerliste|søkere må|apply (now|here|via)|søk (her|nå|via)|"
    r"click (here|apply)|del (stillingen|annonsen)|share this job|report this (job|ad))", re.I)
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,60}\]|\{\{|\}\}|\{[A-Za-z_ ]{2,30}\}|<[A-Za-z_ ]{2,30}>|"
                          r"\bTODO\b|\bTBD\b|\bXXX+\b|\bFIXME\b|lorem ipsum|\.\.\.\s*$", re.I | re.M)
_LEGAL = re.compile(r"\b(as|asa|inc|ltd|llc|ab|gmbh|plc|sa|bv|corp|corporation|co|company|limited|ag|oy|a/s)\b\.?",
                    re.I)


class LetterError(RuntimeError):
    @property
    def user_message(self) -> str:
        return str(self)


# ── profile files ──────────────────────────────────────────
def profile_dir() -> Path:
    return paths.home() / "coverletter"


def letters_root() -> Path:
    return paths.home() / "letters"


def job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[\w-]+", job_id or ""):
        raise LetterError(f"Not a valid job id: {job_id!r}")
    return letters_root() / job_id


def init_profile(force: bool = False) -> list[str]:
    """Copy the example coverletter/ folder into the profile (never overwrites unless force)."""
    src = paths.examples_profile() / "coverletter"
    created = []
    for f in sorted(src.rglob("*")):
        if f.is_file():
            dst = profile_dir() / f.relative_to(src)
            if dst.exists() and not force:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            created.append("coverletter/" + str(f.relative_to(src)))
    (profile_dir() / "samples").mkdir(parents=True, exist_ok=True)
    return created


def load_style() -> dict:
    import yaml
    p = profile_dir() / "style.yaml"
    if not p.exists():
        raise LetterError("No cover letter settings yet. Run 'jobapp coverletter init' first.")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise LetterError(f"coverletter/style.yaml can't be read: {e}") from None
    style = {**DEFAULT_STYLE, **{k: v for k, v in data.items() if v is not None}}
    for k in ("salutation", "sign_off", "subject"):
        if isinstance(style[k], str):
            style[k] = {"en": style[k], "no": style[k]}
        style[k] = {**DEFAULT_STYLE[k], **{str(a): b for a, b in style[k].items()}}
    style["language"] = str(style["language"])
    if style["language"] not in ("en", "no", "auto"):
        raise LetterError("coverletter/style.yaml: language must be en, no or auto.")
    style["max_words"], style["min_words"] = int(style["max_words"]), int(style["min_words"])
    style["banned_phrases"] = [str(b) for b in style.get("banned_phrases") or []]
    style["allow"] = [str(a) for a in style.get("allow") or []]
    return style


def template_tex() -> str:
    p = profile_dir() / "template.tex"
    if not p.exists():
        raise LetterError("No cover letter template yet. Run 'jobapp coverletter init' first.")
    t = p.read_text(encoding="utf-8")
    if t.count(BODY_START) != 1 or t.count(BODY_END) != 1 or t.find(BODY_START) > t.find(BODY_END):
        raise LetterError("coverletter/template.tex needs one '% <<LETTER-BODY>>' … '% <<LETTER-BODY-END>>' pair.")
    return t


# ── resume / ad text ───────────────────────────────────────
def _unescape(s: str) -> str:
    return re.sub(r"\\([&%$#_{}])", r"\1", s)


def resume_plain(tex: str) -> str:
    """Rough detex of the resume body: enough text to trace facts against."""
    m = re.search(r"\\begin\{document\}(.*?)(\\end\{document\}|$)", tex, re.S)
    t = m[1] if m else tex
    t = re.sub(r"(?<!\\)%[^\n]*", "", t)
    t = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\(projentry)\{([^}]*)\}%?\s*\{[^}]*\}", r"\2", t)  # drop the URL argument
    t = re.sub(r"\\\\(\[[^\]]*\])?", "\n", t)
    t = re.sub(r"\\(v|h)space\*?\{[^}]*\}|\\(begin|end)\{[^}]*\}(\[[^\]]*\])?", " ", t)
    t = re.sub(r"\\(item|hfill|noindent|par|newline|centering|small|large|Large|LARGE|footnotesize|"
               r"normalsize|bfseries|itshape|scshape|titlerule|section\*?|subsection\*?)\b", " ", t)
    t = t.replace("~", " ").replace(r"\,", " ").replace(r"\ ", " ").replace("--", "–")
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = _unescape(t).replace("{", " ").replace("}", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def resume_contact(tex: str) -> str:
    """The LaTeX of the resume header's contact group (email/phone/links), reused verbatim."""
    m = re.search(r"\\begin\{document\}.*?\\begin\{center\}(.*?)\\end\{center\}", tex, re.S)
    if not m:
        return ""
    s, groups, depth, start = m[1], [], 0, None
    for i, ch in enumerate(s):
        if ch == "{" and (i == 0 or s[i - 1] != "\\"):
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and (i == 0 or s[i - 1] != "\\"):
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(s[start:i + 1])
    for g in reversed(groups):
        if "@" in g or "href" in g or re.search(r"\d{3}", g):
            inner = re.sub(r"^\{\s*\\small\b", "", g[:-1]).lstrip("{").strip()
            inner = re.sub(r"%\s*$", "", inner.rstrip()).rstrip()
            return "{\\small " + inner + "}"
    return ""


def clean_jd(text: str | None) -> str:
    t, _ = strip_contact(text or "")
    lines = [l for l in t.splitlines() if not _BOILER.search(l)]
    t = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return t[:9000] + (" …" if len(t) > 9000 else "")


def _read_sample(p: Path) -> str:
    suf = p.suffix.lower()
    if suf in (".md", ".txt"):
        return p.read_text(encoding="utf-8", errors="replace")
    if suf == ".docx":
        from .resume.docx_import import _docx_fallback
        return _docx_fallback(p)[1]
    if suf == ".pdf":
        from .resume.pdf_extract import plain_text
        return plain_text(p)
    return ""


def samples(language: str, n: int = 2) -> list[tuple[str, str]]:
    d = profile_dir() / "samples"
    if not d.is_dir():
        return []
    found = []
    for p in d.iterdir():
        if p.is_file() and p.suffix.lower() in (".md", ".txt", ".docx", ".pdf") and not p.name.upper().startswith("README"):
            try:
                t = _read_sample(p).strip()
            except Exception as e:  # noqa: BLE001
                log.warning("sample %s unreadable: %s", p.name, e)
                continue
            if len(t.split()) >= 40:
                found.append((detect_language(t) == language, p.stat().st_mtime, p.name, t))
    found.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(name, t[:3500]) for _, _, name, t in found[:n]]


# ── markdown body ──────────────────────────────────────────
_SALUTE = re.compile(r"^\s*(dear|hei|hi|hello|kjære|to whom|til)\b[^\n]{0,60}[,!:]?\s*$", re.I)
_CLOSE = re.compile(r"^\s*(kind regards|best regards|regards|sincerely|yours sincerely|yours faithfully|"
                    r"best|thank you,|med vennlig hilsen|vennlig hilsen|mvh|beste hilsen)\b", re.I)


def clean_body(text: str) -> tuple[str, list[str]]:
    """Strip code fences, a salutation line and a sign-off block the model added anyway."""
    warnings = []
    m = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", text, re.S)
    t = (m[1] if m else text).strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    paras = [p for p in paras if not re.match(r"^#{1,6}\s", p)]
    if paras and _SALUTE.match(paras[0].splitlines()[0]) and len(paras[0].splitlines()[0]) < 70:
        first = paras[0].splitlines()
        rest = "\n".join(first[1:]).strip()
        paras = ([rest] if rest else []) + paras[1:]
        warnings.append("removed the salutation line (the template adds it)")
    for i, p in enumerate(paras):
        if _CLOSE.match(p) and i >= len(paras) - 2:
            paras = paras[:i]
            warnings.append("removed the sign-off (the template adds it)")
            break
    return "\n\n".join(paras), warnings


def plain(body: str) -> str:
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", body, flags=re.S)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t, flags=re.S)
    t = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", t)
    return t


_TEX_ESC = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "^": r"\^{}", "~": r"\textasciitilde{}"}


def tex_escape(s: str) -> str:
    return "".join(_TEX_ESC.get(c, c) for c in s)


def md_to_latex(body: str) -> str:
    out = []
    for p in re.split(r"\n\s*\n", body.strip()):
        p = " ".join(p.split())
        p = tex_escape(p)
        p = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", p)
        out.append(p)
    return "\n\n".join(out)


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_][\w'’.-]*", plain(text))


# ── rendering ──────────────────────────────────────────────
def letter_date(language: str, d: date | None = None) -> str:
    d = d or date.today()
    if language == "no":
        return f"{d.day}. {MONTHS['no'][d.month - 1]} {d.year}"
    return f"{d.day} {MONTHS['en'][d.month - 1]} {d.year}"


def render_tex(template: str, body: str, *, name: str, contact: str, company: str, role: str,
               language: str, style: dict, today: date | None = None) -> str:
    subject = style["subject"][language].format(role=role, company=company)
    vals = {"<<NAME>>": tex_escape(name), "<<CONTACT>>": contact, "<<DATE>>": letter_date(language, today),
            "<<COMPANY>>": tex_escape(company), "<<SUBJECT>>": tex_escape(subject),
            "<<SALUTATION>>": tex_escape(style["salutation"][language]),
            "<<CLOSING>>": tex_escape(style["sign_off"][language])}
    s = template.index(BODY_START)
    s = template.index("\n", s) + 1
    e = template.rfind("\n", 0, template.index(BODY_END)) + 1
    head, tail = template[:s], template[e:]
    def fill(part: str) -> str:  # comment lines keep their tokens (they document the template)
        out = []
        for line in part.splitlines(keepends=True):
            if not line.lstrip().startswith("%"):
                for k, v in vals.items():
                    line = line.replace(k, v)
            out.append(line)
        return "".join(out)
    return fill(head) + md_to_latex(body) + "\n" + fill(tail)


def letter_txt(body: str, *, name: str, language: str, style: dict) -> str:
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", plain(body).strip())]
    return (style["salutation"][language] + "\n\n" + "\n\n".join(paras) + "\n\n"
            + style["sign_off"][language] + "\n" + name + "\n")


# ── gates ──────────────────────────────────────────────────
@dataclass
class Gate:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    gates: list[Gate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    offenders: list[str] = field(default_factory=list)
    round: int = 0
    words: int = 0
    pdf: Path | None = None
    job_id: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.gates) and all(g.ok for g in self.gates)

    def summary(self) -> str:
        lines = [("✔ " if g.ok else "✘ ") + g.name + (f": {g.detail}" if g.detail else "") for g in self.gates]
        lines += [f"! {w}" for w in self.warnings]
        if self.ok:
            lines.append(f"All checks passed. Run 'jobapp letter {self.job_id} --accept' to make the PDF.")
        elif self.round >= MAX_ROUNDS:
            lines.append(f"Still failing after {self.round} rounds — stop and tell the user (or 'jobapp report-bug').")
        else:
            lines.append(f"Round {self.round} of {MAX_ROUNDS} failed.")
        return "\n".join(lines)

    def fix_report(self) -> str:
        out = ["### Previous attempt failed verification"]
        out += [f"- {g.name}: {g.detail}" for g in self.gates if not g.ok]
        if self.offenders:
            out.append("- Not found in the resume or the job ad (remove or rephrase each one; don't swap in "
                       "another invented fact): " + json.dumps(self.offenders, ensure_ascii=False))
        out.append("Fix ONLY these issues; keep everything else as it was. Output only the body.")
        return "\n".join(out) + "\n"


def _source_index(sources: list[str]) -> str:
    return " " + re.sub(r"\s+", " ", fold(" ".join(sources))) + " "


def _in_source(tok: str, src: str) -> bool:
    t = fold(tok)
    pat = r"(?<![\w])" + re.escape(t) + r"(?![\w])"
    if re.search(pat, src):
        return True
    for stem in (re.sub(r"(’s|'s|s|es)$", "", t),):  # plural/possessive: "Models", Norwegian "BIs"
        acronym = tok[:len(stem)].isupper() and len(stem) >= 2
        if stem and stem != t and (len(stem) >= 3 or acronym) and re.search(r"(?<![\w])" + re.escape(stem) + r"(?![\w])", src):
            return True
    return False


def _number_ok(tok: str, src: str) -> bool:
    pct = tok.endswith("%")
    n = tok.rstrip("%").strip().rstrip(".,")
    groups = re.fullmatch(r"(\d{1,3})((?:[,. \u00a0\u202f]\d{3})+)", n)
    if groups:  # thousands: "2,300" = "2 300" = "2.300" = "2300"
        parts = [groups[1]] + re.findall(r"\d{3}", groups[2])
        e = r"[,.\s\u00a0\u202f]?".join(parts)
        tail = r"\s?(%|percent|prosent)" if pct else r"(?![\d])"
        if re.search(r"(?<![\d.,])" + e + tail, src):
            return True
    variants = {n, n.replace(",", ""), n.replace(",", " "), n.replace(",", "."), n.replace(".", ",")}
    for v in variants:
        if not v:
            continue
        e = re.escape(v).replace(r"\ ", r"[\s\u00a0\u202f]?")
        tail = r"\s?(%|percent|prosent)" if pct else r"(?![\d])"
        if re.search(r"(?<![\d.,])" + e + tail, src):
            return True
    return False


# Norwegian nouns in definite plural etc. ("Fagene", "Oppgavene") are common sentence starters, rarely names.
_NO_SUFFIX = re.compile(r"(ene|ane|heten|ingen|ingene|elsen|ene)$")


def fact_trace(body: str, sources: list[str], allow: set[str], language: str = "en") -> list[str]:
    """Numbers and proper-noun-ish tokens in the body that appear in none of the sources."""
    src = _source_index(sources)
    allow = {fold(a) for a in allow} | _ALLOW
    bad: list[str] = []
    text = plain(body)
    for m in re.finditer(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)(?:\s?%)?\+?|\d[\d,.]*\d(?:\s?%)?\+?|[^\s,;:!?()\"“”«»„]+", text):  # "2,300" is one number
        raw = m.group(0)
        tok = raw.strip(".'’‘\"*[]-–—")
        if not tok:
            continue
        before = text[:m.start()].rstrip(" \t(\"“«*")
        initial = not before or before[-1] in ".!?:\n" or before.endswith("\n\n")
        tok = re.sub(r"(’s|'s)$", "", tok)
        if re.fullmatch(r"\d[\d.,]*%?\+", tok):
            tok = tok[:-1]
        if re.fullmatch(r"\d[\d.,\s\u00a0\u202f]*%?", tok):
            if not _number_ok(tok, src):
                bad.append(tok)
            continue
        if re.search(r"\d", tok):  # ROS2, S3, 2nd, B2B, Q3
            if not _in_source(tok, src) and fold(tok) not in allow:
                bad.append(tok)
            continue
        if _in_source(tok, src) or fold(tok) in allow:  # "Node.js", "Python-based" as a whole
            continue
        for i, part in enumerate(re.split(r"[/–—]|(?<=\w)-(?=\w)", tok)):
            if not part or not re.search(r"[A-ZÆØÅ]|[+#]", part):
                continue
            f = fold(part)
            starter = initial and i == 0 and (f in _STARTERS or (language == "no" and part[1:].islower()
                                                                 and _NO_SUFFIX.search(f)))
            if f in allow or starter or _in_source(part, src):
                continue
            bad.append(part)
    return list(dict.fromkeys(bad))


def _core_company(company: str) -> str:
    c = re.sub(r"\(.*?\)", "", company)
    c = _LEGAL.sub("", c)
    return re.sub(r"\s+", " ", c).strip(" ,.-")


def _core_role(role: str) -> str:
    r = re.sub(r"\(.*?\)|\[.*?\]", "", role)
    r = re.split(r"\s[-–—|]\s|,|\s/\s", r)[0]
    return re.sub(r"\s+", " ", r).strip()


def mentions(body: str, phrase: str) -> bool:
    b = " " + re.sub(r"[\s\-–—/]+", " ", fold(plain(body))) + " "
    p = re.sub(r"[\s\-–—/]+", " ", fold(phrase)).strip()
    return bool(p) and re.search(r"(?<![\w])" + re.escape(p) + r"(?![\w])", b) is not None


def company_mentioned(body: str, company: str) -> bool:
    core = _core_company(company) or company
    short = re.sub(r"\b(group|gruppen|konsernet|norge|norway|norden|nordic|international|global)\b", "", core,
                   flags=re.I).strip(" ,.-")
    return any(v and mentions(body, v) for v in (company, core, short))


def role_mentioned(body: str, role: str) -> bool:
    core = _core_role(role) or role
    if mentions(body, core):
        return True
    sig = [w for w in re.findall(r"[^\W\d_]{3,}", core) if fold(w) not in _STARTERS]
    b = fold(plain(body))
    return bool(sig) and all(re.search(r"(?<!\w)" + re.escape(fold(w)), b) for w in sig)


def check_language(body: str, language: str) -> tuple[bool, str]:
    got = detect_language(plain(body))
    if got == language:
        return True, ""
    return False, (f"the text reads as {LANG_NAMES.get(got, got)}, but it must be {LANG_NAMES[language]}"
                   if got else f"couldn't tell the language; write it clearly in {LANG_NAMES[language]}")


def verify_body(body: str, ctx: dict, style: dict, *, compile_dir: Path | None = None,
                template: str | None = None) -> Report:
    rep = Report(job_id=ctx.get("job_id", ""))
    lang = ctx["language"]
    sources = [ctx["resume"], ctx["jd"], ctx["company"], ctx["role"], ctx.get("location", ""),
               " ".join(ctx.get("keywords", []))]
    allow = set(ctx["name"].split()) | set(style.get("allow") or [])
    offenders = fact_trace(body, sources, allow, lang)
    rep.offenders = offenders
    rep.gates.append(Gate("Facts traceable to resume or ad", not offenders,
                          f"{len(offenders)} not found: {', '.join(offenders[:20])}" if offenders else ""))
    miss = [f"company '{ctx['company']}'" for _ in [0] if not company_mentioned(body, ctx["company"])]
    miss += [f"role '{_core_role(ctx['role'])}'" for _ in [0] if not role_mentioned(body, ctx["role"])]
    rep.gates.append(Gate("Company and role mentioned", not miss, ("missing " + " and ".join(miss)) if miss else ""))
    n = len(words(body))
    rep.words = n
    lo, hi = style["min_words"], style["max_words"]
    rep.gates.append(Gate("Length", lo <= n <= hi,
                          f"{n} words (allowed {lo}–{hi})" + (" — shorten it" if n > hi else " — add substance from the resume" if n < lo else "")))
    fb = fold(plain(body))
    banned = [b for b in style["banned_phrases"]
              if re.search(r"(?<!\w)" + re.escape(fold(b)) + r"(?!\w)", fb)]
    rep.gates.append(Gate("No banned phrases", not banned, ", ".join(f"'{b}'" for b in banned)))
    from .resume.matching import _norm, contains
    kws = ctx.get("matched") or []
    used = [k for k in kws if contains(_norm(plain(body)), plain(body), k)]
    need = min(2, len(kws))
    rep.gates.append(Gate("Uses the ad's matched keywords", len(used) >= need,
                          f"used {len(used)} ({', '.join(used) or 'none'}); need {need} of: {', '.join(kws[:15])}"))
    ok, why = check_language(body, lang)
    rep.gates.append(Gate(f"Language is {LANG_NAMES[lang]}", ok, why))
    ph = sorted({m.group(0).strip() for m in _PLACEHOLDER.finditer(plain(body))})
    rep.gates.append(Gate("No placeholders", not ph, ", ".join(ph)))
    if compile_dir is not None:
        rep.gates.append(_compile_gate(rep, body, ctx, style, compile_dir, template))
    return rep


def _compile_gate(rep: Report, body: str, ctx: dict, style: dict, d: Path, template: str | None) -> Gate:
    from .resume import tex as texmod
    engine = texmod.detect()
    if engine is None:
        return Gate("Compiles to one page", False, "no LaTeX engine (Mac: brew install tectonic)")
    d.mkdir(parents=True, exist_ok=True)
    texf = d / "letter.tex"
    texf.write_text(render_tex(template or template_tex(), body, name=ctx["name"], contact=ctx.get("contact", ""),
                               company=ctx["company"], role=_core_role(ctx["role"]) or ctx["role"],
                               language=ctx["language"], style=style), encoding="utf-8")
    try:
        pdf = texmod.compile_pdf(texf, d, engine)
    except texmod.TexError as e:
        log.error("letter compile failed: %s\n%s", e, e.log[-2000:])
        return Gate("Compiles to one page", False, str(e))
    rep.pdf = pdf
    pages = texmod.page_count(pdf)
    return Gate("Compiles to one page", pages == 1, "" if pages == 1 else f"{pages} pages — shorten the text")


# ── the loop ───────────────────────────────────────────────
def _meta(job_id: str) -> dict:
    p = job_dir(job_id) / "meta.json"
    if not p.exists():
        raise LetterError(f"No cover letter started for this job. Run: jobapp letter {job_id} --prepare")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_meta(job_id: str, meta: dict) -> None:
    (job_dir(job_id) / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def body_path(job_id: str) -> Path:
    return job_dir(job_id) / "body.md"


def fix_report_path(job_id: str) -> Path:
    return job_dir(job_id) / "fix_report.md"


def _context(cfg, conn, job_id: str, language: str | None) -> dict:
    from .resume.keywords import Bank
    from .resume.matching import Matcher
    job = db.get_job(conn, job_id)
    if not job:
        raise LetterError(f"No job with id '{job_id}'.")
    style = load_style()
    tex_path = cfg.resolve(cfg.resume.tex)
    if not tex_path.exists():
        raise LetterError(f"Your resume file wasn't found at {tex_path}.")
    tex = tex_path.read_text(encoding="utf-8")
    jd = clean_jd(job.get("description"))
    lang = language or style["language"]
    if lang == "auto":
        lang = detect_language(jd) or cfg.profile.locale
    if lang not in LANG_NAMES:
        raise LetterError("Language must be 'en' or 'no'.")
    try:
        bank = Bank.load(cfg.resolve(cfg.resume.keywords))
        m = Matcher(bank).score_job(job)
        matched, missing, kw = m.matched, m.missing, bank.all
    except ValueError:
        matched, missing, kw = [], [], []
    return {"job_id": job["id"], "company": job.get("company") or "", "role": job.get("title") or "",
            "location": job.get("location") or "", "language": lang, "matched": matched, "missing": missing[:15],
            "keywords": list(kw), "name": cfg.profile.name, "resume": resume_plain(tex),
            "contact": resume_contact(tex), "jd": jd}


def render_prompt(ctx: dict, style: dict, fix_report: str = "", agent_footer: bool = True) -> str:
    raw = (paths.prompts_dir() / "cover_letter.md").read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->\s*", "", raw, flags=re.S)
    lang = ctx["language"]
    rules = (" Follow Norwegian letter conventions: the subject line \"Søknad på stillingen som …\" and the "
             "sign-off \"Med vennlig hilsen\" are added by the template; write natural bokmål (du/dere-form, "
             "not stiff translation), Norwegian number style (e.g. 12 %)." if lang == "no" else
             " Use plain international English.")
    smp = samples(lang)
    smp_text = "\n\n".join(f"--- {n} ---\n{t}" for n, t in smp) or "(none)"
    vals = {"COMPANY": ctx["company"], "ROLE": ctx["role"], "LOCATION": ctx.get("location") or "-",
            "MATCHED": ", ".join(ctx["matched"]) or "(none)", "MISSING": ", ".join(ctx["missing"]) or "(none)",
            "JD": ctx["jd"] or "(no job description saved — use only the company and role)",
            "RESUME": ctx["resume"], "SAMPLES": smp_text, "TONE": style["tone"],
            "MIN_WORDS": str(style["min_words"]), "MAX_WORDS": str(style["max_words"]),
            "BANNED": "; ".join(f'"{b}"' for b in style["banned_phrases"]),
            "SALUTATION": style["salutation"][lang], "SIGN_OFF": style["sign_off"][lang],
            "LANGUAGE_NAME": LANG_NAMES[lang], "LANGUAGE_RULES": rules, "FIX_REPORT": fix_report.strip()}
    out = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vals.get(m[1], m[0]), raw).rstrip()
    if agent_footer:
        out += (f"\n\n---\n## Where to put your answer (agent mode)\n"
                f"- Write ONLY the body (Markdown paragraphs) to: `{body_path(ctx['job_id'])}`\n"
                f"- Then run: `jobapp letter {ctx['job_id']} --verify`. If it fails, read "
                f"`{fix_report_path(ctx['job_id'])}` and fix ONLY the listed problems (max {MAX_ROUNDS} rounds).\n"
                f"- When it passes: `jobapp letter {ctx['job_id']} --accept`.\n")
    return out + "\n"


def prepare(cfg, conn, job_id: str, language: str | None = None) -> Path:
    ctx = _context(cfg, conn, job_id, language)
    style = load_style()
    template_tex()  # fail early on a broken template
    d = job_dir(ctx["job_id"])
    d.mkdir(parents=True, exist_ok=True)
    for stale in ("body.md", "fix_report.md"):
        (d / stale).unlink(missing_ok=True)
    shutil.rmtree(d / "build", ignore_errors=True)
    (d / "resume.txt").write_text(ctx["resume"], encoding="utf-8")
    (d / "jd.txt").write_text(ctx["jd"], encoding="utf-8")
    meta = {k: ctx[k] for k in ("job_id", "company", "role", "location", "language", "matched", "missing",
                                "keywords", "name", "contact")}
    meta.update(round=0, passed=False, history=[])
    _save_meta(ctx["job_id"], meta)
    p = d / "prompt.md"
    p.write_text(render_prompt(ctx, style), encoding="utf-8")
    return p


def _ctx_from_meta(job_id: str) -> dict:
    meta = _meta(job_id)
    d = job_dir(job_id)
    return {**meta, "resume": (d / "resume.txt").read_text(encoding="utf-8"),
            "jd": (d / "jd.txt").read_text(encoding="utf-8")}


def verify(job_id: str) -> Report:
    ctx = _ctx_from_meta(job_id)
    bp = body_path(job_id)
    if not bp.exists():
        raise LetterError(f"Nothing to check yet: write the letter body to {bp} first.")
    body, warns = clean_body(bp.read_text(encoding="utf-8"))
    if warns:
        bp.write_text(body + "\n", encoding="utf-8")
    style = load_style()
    rep = verify_body(body, ctx, style, compile_dir=job_dir(job_id) / "build")
    rep.warnings += warns
    meta = _meta(job_id)
    meta["round"] = int(meta.get("round", 0)) + 1
    meta["passed"] = rep.ok
    meta["body_sha"] = hashlib.sha1(body.encode()).hexdigest()
    meta.setdefault("history", []).append({"round": meta["round"], "passed": rep.ok, "words": rep.words,
                                           "failed": [g.name for g in rep.gates if not g.ok],
                                           "offenders": rep.offenders})
    _save_meta(job_id, meta)
    rep.round = meta["round"]
    if rep.ok:
        fix_report_path(job_id).unlink(missing_ok=True)
    else:
        fix_report_path(job_id).write_text(rep.fix_report(), encoding="utf-8")
    return rep


def output_paths(cfg, company: str, role: str, language: str) -> tuple[Path, Path]:
    from .resume.service import output_name
    name = output_name(cfg, company, role) + "_CoverLetter" + ("_NO" if language == "no" else "")
    out = paths.output_dir()
    return out / f"{name}.pdf", out / f"{name}.txt"


def load_index() -> dict:
    p = letters_root() / "index.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("letters/index.json unreadable; starting a new one")
    return {}


def _save_index(idx: dict) -> None:
    letters_root().mkdir(parents=True, exist_ok=True)
    p = letters_root() / "index.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def passed(job_id: str) -> bool:
    """The current body.md passed verify and hasn't changed since."""
    try:
        meta = _meta(job_id)
    except LetterError:
        return False
    bp = body_path(job_id)
    body = clean_body(bp.read_text(encoding="utf-8"))[0] if bp.exists() else ""
    return bool(meta.get("passed")) and hashlib.sha1(body.encode()).hexdigest() == meta.get("body_sha") \
        and (job_dir(job_id) / "build" / "letter.pdf").exists()


def accept(cfg, conn, job_id: str) -> tuple[Path, Path]:
    meta = _meta(job_id)
    body = clean_body(body_path(job_id).read_text(encoding="utf-8"))[0] if body_path(job_id).exists() else ""
    if not passed(job_id):
        raise LetterError(f"The letter hasn't passed the checks yet (or changed since). Run 'jobapp letter {job_id} --verify'.")
    built = job_dir(job_id) / "build" / "letter.pdf"
    if not built.exists():
        raise LetterError(f"No PDF built yet. Run 'jobapp letter {job_id} --verify'.")
    pdf, txt = output_paths(cfg, meta["company"] or "Company", meta["role"] or "Role", meta["language"])
    pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, pdf)
    txt.write_text(letter_txt(body, name=meta["name"], language=meta["language"], style=load_style()),
                   encoding="utf-8")
    idx = load_index()
    idx.setdefault(job_id, {})[meta["language"]] = {
        "pdf": str(pdf), "txt": str(txt), "rounds": meta.get("round"), "accepted_at": db.now()}
    _save_index(idx)
    job = db.get_job(conn, job_id)
    if job:
        from .connectors import notify_updated
        notify_updated(cfg, {**job, "cover_letter": str(pdf)}, {"cover_letter": str(pdf)})
    return pdf, txt


def status(job_id: str) -> dict:
    """What the dashboard shows: none | needs_claude | failing | passed | ready (+ files)."""
    idx = load_index().get(job_id, {})
    out: dict = {"job_id": job_id, "letters": {}}
    for lang, rec in idx.items():
        p, t = Path(rec["pdf"]), Path(rec["txt"])
        if p.exists():
            out["letters"][lang] = {**rec, "text": t.read_text(encoding="utf-8") if t.exists() else ""}
    d = job_dir(job_id)
    if (d / "meta.json").exists():
        meta = _meta(job_id)
        out.update(language=meta["language"], round=meta.get("round", 0), prompt=str(d / "prompt.md"))
        if meta.get("passed"):
            out["draft"] = "passed"
        elif body_path(job_id).exists() and meta.get("round"):
            out["draft"] = "failing"
        else:
            out["draft"] = "needs_claude"
    out["state"] = "ready" if out["letters"] else out.get("draft", "none")
    return out


# ── API mode ───────────────────────────────────────────────
def run_api(cfg, conn, job_id: str, language: str | None = None, call=None) -> Report:
    from .resume.docx_import import api_caller
    call = call or api_caller()
    if call is None:
        raise LetterError(f"No ANTHROPIC_API_KEY or GEMINI_API_KEY found. Use agent mode: jobapp letter {job_id} --prepare")
    prepare(cfg, conn, job_id, language)
    ctx, style = _ctx_from_meta(job_id), load_style()
    fix, rep = "", Report()
    for _ in range(MAX_ROUNDS):
        answer = call(render_prompt(ctx, style, fix, agent_footer=False))
        body_path(job_id).write_text(clean_body(answer)[0] + "\n", encoding="utf-8")
        rep = verify(job_id)
        if rep.ok:
            break
        fix = rep.fix_report() + "\nYour previous body:\n```markdown\n" + body_path(job_id).read_text(encoding="utf-8") + "```\n"
    return rep
