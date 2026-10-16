"""PDF resume extraction for the import pipeline.

Text comes from `pdftotext -layout` (fallback: pypdf), links from the PDF's link annotations (pypdf),
page count from pypdf. Bold/italic can't be recovered from a PDF, which the layout facts say.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

from ..tools import which

# Glyphs PDFs use as bullets. Some fonts without a Unicode map extract them as letters
# (Wingdings "§"/"Ø", or "o" for a hollow sub-bullet) — only stripped at the start of a line.
BULLET_GLYPHS = "•●▪■◦○◆◇►▸▹‣⁃∙·➢➤✓✔❖–—*-§Ø\uf0b7\uf0a7\uf076\uf0d8\uf0fc"
_BULLET_RE = re.compile(rf"^(\s*)(?:[{re.escape(BULLET_GLYPHS)}]|o(?=\s+[A-Z0-9]))\s+")
_LABEL = re.compile(r"^[^:\[\]]{2,40}:\s")  # "Languages: ..." style lines (Skills)
GAP = " ⇥ "  # marks a wide horizontal gap in -layout output (right-aligned dates/locations)
HEADINGS = {
    "education", "experience", "work experience", "professional experience", "employment", "projects",
    "skills", "technical skills", "core competencies", "certifications", "awards", "publications",
    "languages", "leadership", "volunteering", "interests", "summary", "profile", "objective",
    "activities", "honors", "research", "courses", "coursework", "references",
}


def _pdftotext(pdf: Path, layout: bool, extra: list[str] | None = None) -> str | None:
    exe = which("pdftotext")
    if not exe:
        return None
    cmd = [exe, "-enc", "UTF-8"] + (["-layout"] if layout else []) + (extra or []) + [str(pdf), "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _pypdf_text(pdf: Path, layout: bool) -> str:
    from pypdf import PdfReader
    out = []
    for p in PdfReader(str(pdf)).pages:
        try:
            out.append(p.extract_text(extraction_mode="layout") if layout else p.extract_text())
        except Exception:  # noqa: BLE001 — old pypdf / odd page
            out.append(p.extract_text() or "")
    return "\f".join(x or "" for x in out)


def layout_text(pdf: Path) -> tuple[str, bool]:
    t = _pdftotext(pdf, layout=True)
    return (t, True) if t is not None else (_pypdf_text(pdf, layout=True), False)


def plain_text(pdf: Path) -> str:
    """Text for the word check. `-raw` keeps line-end hyphens (see docx_import.pdf_text)."""
    t = _pdftotext(pdf, layout=False, extra=["-raw"])
    return t if t is not None else _pypdf_text(pdf, layout=False)


def pages(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)


def _norm_url(u: str) -> str:
    return u.strip().rstrip("/")


def _words(pdf: Path) -> dict[int, list[tuple[float, float, str]]]:
    """{page_index: [(x_center, y_center, word)]} in top-left-origin points, via `pdftotext -bbox`."""
    import html
    xml = _pdftotext(pdf, layout=False, extra=["-bbox"]) or ""
    out: dict[int, list[tuple[float, float, str]]] = {}
    for i, page in enumerate(re.split(r"<page ", xml)[1:]):
        out[i] = [((float(m[1]) + float(m[3])) / 2, (float(m[2]) + float(m[4])) / 2, html.unescape(m[5]))
                  for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" '
                                       r'yMax="([\d.]+)">([^<]*)</word>', page)]
    return out


def links(pdf: Path) -> list[dict]:
    """[{url, text, page}] from /Link annotations with a /URI action, in page order.
    `text` = the words whose centre lies inside the link box (empty if pdftotext is missing)."""
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    words = None
    out = []
    for i, page in enumerate(r.pages):
        height = float(page.mediabox.height)
        for a in page.get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") != "/Link":
                continue
            act = a.get("/A")
            act = act.get_object() if act is not None else None
            uri = act.get("/URI") if act is not None else None
            if not uri:
                continue
            uri = uri.decode("utf-8", "replace") if isinstance(uri, bytes) else str(uri)
            x1, y1, x2, y2 = (float(v) for v in a["/Rect"])
            top, bottom = height - max(y1, y2), height - min(y1, y2)
            if words is None:
                words = _words(pdf)
            text = " ".join(w for cx, cy, w in words.get(i, [])
                            if min(x1, x2) <= cx <= max(x1, x2) and top <= cy <= bottom)
            out.append({"url": _norm_url(uri), "text": text, "page": i + 1})
    return out


def urls(pdf: Path) -> set[str]:
    return {link["url"] for link in links(pdf)}


def _font_facts(pdf: Path) -> dict:
    """Most common font size on page 1, weighted by characters."""
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    sizes: Counter = Counter()
    for page in r.pages[:1]:
        def visit(text, cm, tm, font_dict, font_size):
            if not text.strip():
                return
            scale = abs(tm[3] * cm[3]) or 1.0
            sizes[round(font_size * scale * 2) / 2] += len(text.strip())
        try:
            page.extract_text(visitor_text=visit)
        except Exception:  # noqa: BLE001
            return {}
    out: dict = {}
    if sizes:
        out["base_font_pt"] = sizes.most_common(1)[0][0]
    return out


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 45 or GAP.strip() in s or s.endswith((".", ",", ";")):
        return False
    if s.casefold() in HEADINGS:
        return True
    words = re.sub(r"[&/,]", " ", s).split()
    letters = re.sub(r"[^A-Za-z]", "", s)
    if letters and letters.isupper() and len(letters) >= 4 and len(words) <= 5:
        return True
    # "Certifications & Recognition", "Professional Engagement & Leadership": a known heading word inside
    return len(words) <= 5 and all(w[:1].isupper() for w in words) and \
        any(w.casefold() in HEADINGS for w in words) and not re.search(r"\d", s)


def to_markdown(text: str, link_list: list[dict] | None = None) -> str:
    """Turn `pdftotext -layout` output into markdown-ish text: `## ` headings, `- ` bullets
    (continuation lines joined), wide gaps shown as ⇥, links as [text](url)."""
    out: list[str] = []
    bullet_indent: int | None = None
    for raw in text.replace("\f", "\n").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        m = _BULLET_RE.match(line)
        body = re.sub(r"\s{3,}", GAP, line[m.end():] if m else line.strip()).strip()
        if m:
            out.append("- " + body)
            bullet_indent = m.end()
        elif bullet_indent is not None and indent >= bullet_indent - 1 and not _is_heading(line):
            out[-1] += ("" if out[-1].endswith("-") else " ") + body
        elif out and not out[-1].startswith("## ") and not _is_heading(line) and GAP.strip() not in body \
                and not _LABEL.match(body) and (out[-1].endswith(",") or _LABEL.match(out[-1])):
            out[-1] += " " + body  # wrapped plain line (e.g. a long Skills line)
        elif _is_heading(line):
            out.append("")
            out.append("## " + body)
            bullet_indent = None
        else:
            out.append(body)
            bullet_indent = None
    md = "\n".join(out).strip()
    for link in link_list or []:
        anchor = link.get("text") or ""
        if not anchor:
            continue
        # first occurrence as a whole word that isn't already inside a [..](..) link
        m = re.search(rf"(?<![\w\[/.@]){re.escape(anchor)}(?![\w\]])", md)
        if m:
            md = md[:m.start()] + f"[{anchor}]({link['url']})" + md[m.end():]
    unplaced = [link for link in link_list or [] if f"]({link['url']})" not in md]
    if unplaced:
        md += "\n\n<!-- links whose anchor text could not be located -->\n" + "\n".join(
            f"- link: [{link.get('text') or '?'}]({link['url']}) (page {link['page']})" for link in unplaced)
    return md + "\n"


def strip_bullets(text: str) -> str:
    """Plain text for the token diff: drop bullet glyphs at line starts (allowlist, not content)."""
    return "\n".join(_BULLET_RE.sub(r"\1", ln) for ln in text.splitlines())


def layout_facts(pdf: Path, md: str, used_pdftotext: bool) -> dict:
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    box = r.pages[0].mediabox
    out: dict = {
        "source_format": "pdf",
        "note": ("Source is a PDF: bold/italic and exact spacing are NOT recoverable from it, so the "
                 "markdown has no **bold**/*italic*. Use the template's own emphasis (entry macros) instead. "
                 f"'{GAP.strip()}' marks a wide horizontal gap in the PDF (usually a right-aligned date or "
                 "place) — it is not text, never copy it."),
        "page_size_in": [round(float(box.width) / 72, 2), round(float(box.height) / 72, 2)],
        "text_extractor": "pdftotext -layout" if used_pdftotext else "pypdf",
    }
    out.update(_font_facts(pdf))
    out["section_order"] = [ln[3:].strip() for ln in md.splitlines() if ln.startswith("## ")]
    out["links"] = len(links(pdf))
    return out
