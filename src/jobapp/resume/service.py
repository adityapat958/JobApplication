"""Build a tailored PDF for a saved job."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import db, paths
from ..log import get
from . import tex as texmod
from .build import tailor
from .keywords import Bank
from .matching import Matcher

log = get("build")


class BuildError(RuntimeError):
    @property
    def user_message(self) -> str:
        return str(self)


@dataclass
class BuildResult:
    pdf: Path
    matched: list[str]
    missing: list[str]
    core: list[str]
    tech: list[str]
    pages: int | None = None
    warnings: list[str] = field(default_factory=list)
    variant: str | None = None


_TRANS = str.maketrans({"æ": "ae", "Æ": "Ae", "ø": "o", "Ø": "O", "å": "a", "Å": "A", "ß": "ss"})


def slug_part(s: str, maxlen: int = 40) -> str:
    s = (s or "").translate(_TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", "", s)
    words = re.findall(r"[A-Za-z0-9]+", s)
    out = "-".join(words)
    return out[:maxlen].strip("-") or "x"


def output_name(cfg, company: str, role: str) -> str:
    vals = {"first": slug_part(cfg.profile.first), "last": slug_part(cfg.profile.last),
            "company": slug_part(company, 30), "role": slug_part(role, 40), "date": date.today().isoformat()}
    name = cfg.resume.output_name.format(**vals)
    name = re.sub(r"_+", "_", name.replace("_x_", "_")).strip("_")
    return name


def _page_target(tex_path: Path, engine) -> int | None:
    """Page count of the untouched resume (cached by content hash)."""
    content = tex_path.read_bytes()
    h = hashlib.sha1(content).hexdigest()[:16]
    cache = paths.output_dir() / ".cache" / "pages.json"
    data = {}
    if cache.exists():
        try:
            data = json.loads(cache.read_text())
        except ValueError:
            data = {}
    if h in data:
        return data[h]
    with tempfile.TemporaryDirectory() as td:
        t = Path(td) / "original.tex"
        t.write_bytes(content)
        _copy_assets(tex_path.parent, Path(td))
        try:
            n = texmod.page_count(texmod.compile_pdf(t, Path(td), engine))
        except texmod.TexError:
            return None
    data[h] = n
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return n


def _copy_assets(src_dir: Path, dst: Path) -> None:
    """Images / .cls / .sty next to the resume are needed to compile it."""
    for f in src_dir.iterdir():
        if f.is_file() and f.suffix.lower() in (".cls", ".sty", ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".bib"):
            shutil.copy2(f, dst / f.name)


def build_pdf(cfg, *, company: str, role: str, description: str | None, title: str = "",
              location: str = "", out_dir: Path | None = None, dry_run: bool = False,
              variant: str | None = None) -> BuildResult:
    """variant: with resume.variants, the resume to use (None = pick from the title/description)."""
    from .variants import auto_pick, resume_for
    job = {"description": description, "title": title or role, "company": company, "location": location}
    if cfg.resume.variants and variant is None:
        variant = auto_pick(cfg, job)
    try:
        res = resume_for(cfg, variant if cfg.resume.variants else None)
    except KeyError:
        raise BuildError(f"'{variant}' isn't one of your resumes ({', '.join(cfg.resume.variants)}).") from None
    tex_path = res.tex
    if not tex_path.exists():
        raise BuildError(f"Your resume file wasn't found at {tex_path}.")
    try:
        bank = Bank.load(res.keywords)
    except ValueError as e:
        raise BuildError(str(e)) from None
    m = Matcher(bank).score_job(job)
    original = tex_path.read_text(encoding="utf-8")
    try:
        t = tailor(original, bank, m.core, m.tech)
    except ValueError as e:
        raise BuildError(str(e)) from None
    out_dir = Path(out_dir or paths.output_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    name = output_name(cfg, company, role)
    warnings: list[str] = []
    if not description:
        warnings.append("No job description saved, so only the job title was used for keywords.")
    if dry_run:
        return BuildResult(out_dir / f"{name}.pdf", m.matched, m.missing, t.core, t.tech, None, warnings, variant)
    engine = texmod.detect()
    if engine is None:
        raise BuildError("No LaTeX engine found. On a Mac run 'brew install tectonic' (or ask Claude to set it up).")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        tmp_tex = work / f"{name}.tex"
        tmp_tex.write_text(texmod.keep_headings(t.tex), encoding="utf-8")
        _copy_assets(tex_path.parent, work)
        try:
            pdf = texmod.compile_pdf(tmp_tex, work, engine)
        except texmod.TexError as e:
            log.error("compile failed: %s\n%s", e, e.log[-3000:])
            raise BuildError(f"Couldn't make the PDF: {e}. Your resume file itself may have a LaTeX error.") from None
        pages = texmod.page_count(pdf)
        dest = out_dir / f"{name}.pdf"
        shutil.copy2(pdf, dest)
    target = _page_target(tex_path, engine)
    if target and pages != target:
        warnings.append(f"The tailored resume has {pages} page(s) but your original has {target}. "
                        "Check it before sending.")
    return BuildResult(dest, m.matched, m.missing, t.core, t.tech, pages, warnings, variant)


def build_for_job(cfg, conn, job_id: str) -> BuildResult:
    from .variants import pick
    job = db.get_job(conn, job_id)
    if not job:
        raise BuildError(f"No job with id '{job_id}'.")
    res = build_pdf(cfg, company=job["company"] or "Company", role=job["title"] or "Role",
                    description=job.get("description"), title=job["title"] or "", location=job["location"] or "",
                    variant=pick(cfg, job))
    db.add_build(conn, job["id"], str(res.pdf), res.matched)
    from ..connectors import notify_updated
    notify_updated(cfg, db.get_job(conn, job["id"]), {"built": str(res.pdf)})
    return res


def choose_variant(cfg, conn, job_id: str, name: str | None) -> dict:
    """Save which resume a job uses ('auto'/None = automatic) and re-score it. ValueError on a bad name."""
    from .rescore import rescore_all
    from .variants import validate_choice
    job = db.get_job(conn, job_id)
    if not job:
        raise ValueError(f"No job with id '{job_id}'.")
    v = validate_choice(cfg, name)
    db.set_variant(conn, job["id"], v)
    rescore_all(cfg, conn, ids=[job["id"]])
    return db.get_job(conn, job["id"])
