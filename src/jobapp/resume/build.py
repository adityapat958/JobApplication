"""Tailor the Skills lines between the SKILLS markers. Every other byte of the .tex is left alone."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .keywords import Bank

CORE = ("% <<SKILLS-CORE>>", "% <<SKILLS-CORE-END>>")
TECH = ("% <<SKILLS-TECH>>", "% <<SKILLS-TECH-END>>")

_ESC = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}


def latex_escape(s: str) -> str:
    return re.sub(r"(?<!\\)[&%$#_]", lambda m: _ESC[m[0]], s)


def latex_unescape(s: str) -> str:
    return re.sub(r"\\([&%$#_])", r"\1", s)


def _find(tex: str, start: str, end: str) -> list[tuple[int, int]]:
    """(content_start, content_end) spans strictly between the marker lines."""
    spans = []
    for m in re.finditer(re.escape(start) + r"[^\n]*\n", tex):
        e = tex.find(end, m.end())
        if e == -1:
            continue
        line_start = tex.rfind("\n", 0, e) + 1
        spans.append((m.end(), line_start))
    return spans


def check_markers(tex: str) -> None:
    core = _find(tex, *CORE)
    if tex.count(CORE[0]) != 1 or tex.count(CORE[1]) != 1 or len(core) != 1:
        raise ValueError("resume.tex needs exactly one '% <<SKILLS-CORE>>' … '% <<SKILLS-CORE-END>>' pair")
    if tex.count(TECH[0]) != tex.count(TECH[1]) or tex.count(TECH[0]) > 1:
        raise ValueError("resume.tex has an unmatched '% <<SKILLS-TECH>>' marker")
    for (s, e) in core + _find(tex, *TECH):
        if not _ITEM.search(tex[s:e]):
            raise ValueError("a SKILLS block has no '\\item {…\\textbf{Label:} …}' line inside")


NOHYPH = "\\language=255 "
# \item {\small\textbf{Core Competencies:} a, b, c}
_ITEM = re.compile(r"(?P<indent>[ \t]*)\\item\s*\{(?P<pre>[^{}]*?\\textbf\{(?P<label>[^{}]*)\})(?P<body>.*?)\}[ \t]*(?:\n|$)",
                   re.S)


def _strip_comments(s: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", s)


def parse_items(body: str) -> list[str]:
    text = _strip_comments(body)
    text = re.sub(r"\s+", " ", text)
    parts, depth, cur = [], 0, ""
    for ch in text:  # split on commas outside parentheses: "AWS (ECS, IAM), Docker" -> 2 items
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth <= 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [latex_unescape(x.strip()) for x in parts if x.strip()]


@dataclass
class Block:
    start: int
    end: int
    indent: str
    pre: str
    label: str
    items: list[str]
    item_span: tuple[int, int]  # span of the first \item inside the block (absolute)

    @property
    def budget(self) -> int:
        return len(", ".join(self.items))


def read_block(tex: str, markers: tuple[str, str]) -> Block | None:
    spans = _find(tex, *markers)
    if not spans:
        return None
    s, e = spans[0]
    m = _ITEM.search(tex, s, e)
    if not m:
        raise ValueError(f"no \\item line between {markers[0]} markers")
    return Block(s, e, m["indent"], m["pre"], m["label"], parse_items(m["body"]), (m.start(), m.end()))


def choose(matched: list[str], original: list[str], bank_items: list[str], budget: int,
           slack: float = 1.05, shown_elsewhere: set[str] | None = None) -> list[str]:
    """JD-matched first, then the user's original picks, then the rest of the bank, up to the length budget.
    Keywords already listed on another (unmarked) Skills line are not repeated."""
    out: list[str] = []
    length = 0
    limit = int(budget * slack)
    skip = {k.casefold() for k in shown_elsewhere or ()} - {k.casefold() for k in original}
    # "AWS" (from the ad or the bank) and the user's own "AWS (ECS, IAM)" are the same skill: keep theirs
    head = {re.sub(r"\s*\(.*$", "", o).casefold(): o for o in original}
    for o in original:  # ... and "ECS" is already shown inside "AWS (ECS/Fargate, IAM)"
        for inner in re.findall(r"\(([^()]*)\)", o):
            skip |= {x.strip().casefold() for x in re.split(r"[,/]", inner) if x.strip()}
    for kw in list(dict.fromkeys(head.get(k.casefold(), k) for k in matched + original + bank_items)):
        if kw.casefold() in skip:
            continue
        add = len(kw) + (2 if out else 0)
        if length + add > limit:
            if kw in matched and not out:
                pass
            else:
                continue
        out.append(kw)
        length += add
    return out


def render_item(block: Block, items: list[str], width: int = 92) -> str:
    # no hyphenation in keyword lines ("statis-/tics" reads as two words to an ATS): language 255
    # has no patterns; it is local to the group, so the rest of the resume hyphenates as before
    pre = block.pre if NOHYPH in block.pre else NOHYPH + block.pre
    head = f"{block.indent}\\item {{{pre}"
    lines, cur = [], ""
    body_indent = block.indent + "    "
    for i, kw in enumerate(items):
        piece = latex_escape(kw) + ("," if i < len(items) - 1 else "}")
        if cur and len(body_indent) + len(cur) + 1 + len(piece) > width:
            lines.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}" if cur else piece
    lines.append(cur or "}")
    return head + "\n" + "\n".join(body_indent + l for l in lines) + "\n"


@dataclass
class Tailored:
    tex: str
    core: list[str]
    tech: list[str]


def other_skill_items(tex: str) -> set[str]:
    """Items on `\\item {\\textbf{Label:} a, b}` Skills lines outside the markers (multi-line Skills sections)."""
    found: set[str] = set()
    for part in outside_markers(tex).split("\x00"):
        for m in _ITEM.finditer(part):
            for item in parse_items(m["body"]):
                found.add(item)
                found.update(x.strip() for x in re.split(r"[()/]", item) if x.strip())  # "AWS (ECS, IAM)"
    return found


def tailor(tex: str, bank: Bank, matched_core: list[str], matched_tech: list[str]) -> Tailored:
    check_markers(tex)
    elsewhere = other_skill_items(tex)
    out = tex
    chosen_core: list[str] = []
    chosen_tech: list[str] = []
    # Rewrite the later block first so earlier offsets stay valid.
    blocks = []
    for markers, matched, bank_items in ((CORE, matched_core, bank.core), (TECH, matched_tech, bank.tech)):
        b = read_block(tex, markers)
        if b:
            blocks.append((b, matched, bank_items, markers))
    if len(blocks) == 1:  # CORE only: everything goes on one line
        b, _, _, m = blocks[0]
        blocks = [(b, matched_core + matched_tech, bank.core + bank.tech, m)]
    for b, matched, bank_items, markers in sorted(blocks, key=lambda x: -x[0].start):
        items = choose(matched, b.items, bank_items, b.budget, shown_elsewhere=elsewhere)
        s, e = b.item_span
        out = out[:s] + render_item(b, items) + out[e:]
        if markers == CORE:
            chosen_core = items
        else:
            chosen_tech = items
    return Tailored(out, chosen_core, chosen_tech)


def outside_markers(tex: str) -> str:
    """Everything except the content between marker lines (for byte-identity checks)."""
    parts, pos = [], 0
    spans = sorted(_find(tex, *CORE) + _find(tex, *TECH))
    for s, e in spans:
        parts.append(tex[pos:s])
        pos = e
    parts.append(tex[pos:])
    return "\x00".join(parts)
