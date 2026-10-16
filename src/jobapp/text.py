"""Small text helpers: HTML→text, job type guessing, language detection, EN/NO date parsing."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
        tag.insert_after("\n")
    for li in soup.find_all("li"):
        li.insert_before("• ")
    text = soup.get_text()
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def fold(s: str) -> str:
    """lowercase + strip accents, but keep æ ø å (they are letters, not accents)."""
    s = s.lower()
    out = []
    for ch in s:
        if ch in "æøå":
            out.append(ch)
            continue
        d = unicodedata.normalize("NFKD", ch)
        out.append("".join(c for c in d if not unicodedata.combining(c)))
    return "".join(out)


_TYPE_PATTERNS = [
    ("internship", r"\b(intern|interns|internship|co-?op|praktikant|praktikum|sommerjobb|summer job|sommerstudent|"
                   r"sommerpraktikant|werkstudent|working student)\b"),
    ("parttime", r"\b(part[- ]?time|deltid|deltidsstilling|ekstrahjelp)\b"),
    ("contract", r"\b(contract|contractor|konsulentoppdrag)\b"),
    ("temporary", r"\b(temporary|vikariat|vikar|engasjement|midlertidig)\b"),
]


def guess_job_type(*texts: str | None) -> str:
    t = fold(" ".join(x for x in texts if x))
    for name, pat in _TYPE_PATTERNS:
        if re.search(pat, t):
            return name
    return ""


def normalize_job_type(value: str | None) -> str:
    v = fold(value or "").replace("_", "-").strip()
    table = {
        "full-time": "fulltime", "fulltime": "fulltime", "full time": "fulltime", "fast": "fulltime",
        "heltid": "fulltime", "permanent": "fulltime", "fast stilling": "fulltime",
        "internship": "internship", "intern": "internship", "praksisplass": "internship",
        "part-time": "parttime", "parttime": "parttime", "part time": "parttime", "deltid": "parttime",
        "contract": "contract", "contractor": "contract", "temporary": "temporary", "vikariat": "temporary",
        "engasjement": "temporary", "midlertidig": "temporary", "seasonal": "temporary",
    }
    return table.get(v, "")


_NO_WORDS = set("og i er det som på en til med for av vi du har at deg ikke våre oss eller kan skal om "
                "hos ved stillingen søker erfaring arbeid jobb kunder".split())
_EN_WORDS = set("the and to of in you we our with for is are will a on as be your this that have "
                "experience work team role skills".split())


def detect_language(text: str | None) -> str | None:
    if not text:
        return None
    words = re.findall(r"[a-zæøå]+", text.lower())
    if len(words) < 8:
        return None
    no = sum(w in _NO_WORDS for w in words) + 2 * len(re.findall(r"[æøå]", text.lower())) / 5
    en = sum(w in _EN_WORDS for w in words)
    if max(no, en) < 3:
        return None
    return "no" if no > en else "en"


NO_MONTHS = {"januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8,
             "september": 9, "oktober": 10, "november": 11, "desember": 12,
             "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
             "okt": 10, "nov": 11, "des": 12}
EN_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], 1)}
EN_MONTHS.update({k[:3]: v for k, v in EN_MONTHS.items()})
EN_MONTHS["sept"] = 9


def parse_date(s: str | None) -> date | None:
    """ISO, 15.10.2026, '15. oktober 2026', 'October 15, 2026', '15 Oct 2026'. None if unparseable."""
    if not s:
        return None
    t = fold(s.strip())
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b", t)
    if m:
        y = int(m[3]); y = y + 2000 if y < 100 else y
        return _mk(y, int(m[2]), int(m[1]))
    m = re.search(r"\b(\d{1,2})\.?\s+([a-zæøå]+)\.?,?\s+(\d{4})\b", t)
    if m:
        mon = NO_MONTHS.get(m[2]) or EN_MONTHS.get(m[2])
        if mon:
            return _mk(int(m[3]), mon, int(m[1]))
    m = re.search(r"\b([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\b", t)
    if m:
        mon = EN_MONTHS.get(m[1]) or NO_MONTHS.get(m[1])
        if mon:
            return _mk(int(m[3]), mon, int(m[2]))
    return None


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


_REL_UNITS = {
    "minute": 1 / 1440, "min": 1 / 1440, "minutt": 1 / 1440, "minutter": 1 / 1440,
    "hour": 1 / 24, "time": 1 / 24, "timer": 1 / 24,
    "day": 1, "dag": 1, "dager": 1, "d": 1,
    "week": 7, "uke": 7, "uker": 7, "w": 7,
    "month": 30, "måned": 30, "måneder": 30, "mnd": 30, "mo": 30,
    "year": 365, "år": 365, "y": 365,
}


def parse_relative(s: str | None, now: datetime | None = None) -> datetime | None:
    """'3 days ago', '1 week ago', '7 dager siden', '14 timer siden', '0d', '2mo'."""
    if not s:
        return None
    now = now or datetime.now(timezone.utc)
    t = fold(s.strip())
    if t in ("today", "i dag", "just now", "nettopp"):
        return now
    if t in ("yesterday", "i går"):
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\s*([a-zæøå]+)", t)
    if not m:
        return None
    unit = m[2].rstrip("s") if m[2] not in _REL_UNITS else m[2]
    days = _REL_UNITS.get(unit) or _REL_UNITS.get(m[2])
    if days is None:
        return None
    return now - timedelta(days=int(m[1]) * days)


def to_datetime(d: date | datetime | None) -> datetime | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return to_datetime(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        d = parse_date(s)
        return to_datetime(d) if d else None


# ── contact section (names/phones/emails are not skills) ──────────────────
_CONTACT_HEAD = re.compile(
    r"^\W*(kontaktpersoner|kontaktperson|kontaktinformasjon|kontakt oss|kontakt|contact persons?|"
    r"contact information|contact details|contact us|contacts?|spørsmål om stillingen|"
    r"questions about (?:the|this) (?:position|role|job))\b\s*:?\s*(.*)$", re.I)
_ALWAYS_CONTACT = re.compile(r"^\W*(spørsmål om stillingen|questions about (?:the|this) (?:position|role|job))", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# +47 912 34 567 | 22 33 44 55 | 91234567 | (555) 123-4567 — but not "2024-2026"
_PHONE = re.compile(r"(?<![\w-])(?:\+\d{1,3}[\s.]?\d[\d\s.-]{6,}\d|\d{8}|\d{2,3}(?:[\s.]\d{2,3}){3}|\d{3}[\s.]\d{2}[\s.]\d{3}"
                    r"|\(\d{3}\)\s?\d{3}-\d{4}|\d{3}-\d{3}-\d{4})(?![\w-])")
_PHONE_LABEL = re.compile(r"^\W*(tlf|telefon|mobil|mob|phone|tel|mobile|e-?post|e-?mail|epost)\b\.?\s*:?", re.I)
_SECTION = re.compile(r"^\W*(kvalifikasjoner|arbeidsoppgaver|vi tilbyr|om oss|om stillingen|om arbeidsgiver\w*|"
                      r"personlige egenskaper|qualifications|responsibilities|requirements|what we offer|"
                      r"about (?:us|the role|the company)|benefits)\b", re.I)
_NAME = re.compile(r"\b([A-ZÆØÅ][a-zæøåäöüéèáó'’-]+(?:\s+(?:van|von|de|der)?\s*[A-ZÆØÅ][a-zæøåäöüéèáó'’-]+){1,2})\b")
_NAME_AFTER = re.compile(r"\b(?:til|to|kontakt|contact|med|with)\s+" + _NAME.pattern)


def _contactish(line: str) -> bool:
    return bool(_EMAIL.search(line) or _PHONE.search(line) or _PHONE_LABEL.match(line))


def strip_contact(text: str | None) -> tuple[str, list[str]]:
    """Remove the contact block (Kontaktperson / Contact / Spørsmål om stillingen + the short lines under it)
    and phone/email lines. Returns (text without them, person names seen there)."""
    if not text:
        return text or "", []
    keep: list[str] = []
    block: list[str] = []
    in_block = 0  # lines left to consume in a contact block
    for line in text.splitlines():
        s = line.strip()
        m = _CONTACT_HEAD.match(s)
        if m and (not m[2] or s.endswith(":") or len(m[2].split()) <= 8 or _ALWAYS_CONTACT.match(s)):
            block.append(m[2])
            in_block = 10
            continue
        if _ALWAYS_CONTACT.match(s) or _contactish(s):
            block.append(s)
            continue
        if in_block and s:
            short = len(s.split()) <= 8 and not s.startswith(("•", "-", "*", "–")) and not _SECTION.match(s)
            if short and not s.endswith(":"):
                block.append(s)
                in_block -= 1
                continue
            in_block = 0
        keep.append(line)
    names: list[str] = []
    for b in block:
        first = re.split(r"[,|–—(]| - ", b)[0].strip()
        cands = [m[1] for m in _NAME_AFTER.finditer(b)]
        if _NAME.fullmatch(first):
            cands.append(first)
        for n in cands:
            n = re.sub(r"\s+", " ", n).strip()
            if n not in names:
                names.append(n)
    out = "\n".join(keep)
    for n in names:  # the same person mentioned elsewhere in the ad
        out = re.sub(r"\b" + re.escape(n).replace(r"\ ", r"\s+") + r"\b", "\n", out)
    return out, names
