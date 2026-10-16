"""LaTeX engine abstraction: tectonic if present, else latexmk, else pdflatex."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..tools import which


class TexError(RuntimeError):
    def __init__(self, message: str, log: str = ""):
        super().__init__(message)
        self.log = log


@dataclass
class Engine:
    name: str
    path: str

    def command(self, tex: Path, outdir: Path) -> list[str]:
        if self.name == "tectonic":
            return [self.path, "--keep-logs", "--outdir", str(outdir), str(tex)]
        if self.name == "latexmk":
            return [self.path, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
                    f"-outdir={outdir}", str(tex)]
        return [self.path, "-interaction=nonstopmode", "-halt-on-error",
                f"-output-directory={outdir}", str(tex)]


def detect(prefer: str | None = None) -> Engine | None:
    order = ["tectonic", "latexmk", "pdflatex"]
    if prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    for name in order:
        p = which(name)
        if p:
            if name == "latexmk" and not which("pdflatex"):
                continue
            return Engine(name, p)
    return None


def first_error(log: str) -> str:
    m = re.search(r"^! (.+?)$(?:.*?^l\.(\d+))?", log, re.MULTILINE | re.DOTALL)
    if m:
        line = f" (line {m[2]})" if m[2] else ""
        return f"{m[1].strip()}{line}"
    m = re.search(r"^error: (.+)$", log, re.MULTILINE)
    return m[1].strip() if m else "unknown LaTeX error"


def compile_pdf(tex: Path, outdir: Path | None = None, engine: Engine | None = None,
                timeout: int = 180) -> Path:
    tex = Path(tex).resolve()
    outdir = Path(outdir or tex.parent).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    engine = engine or detect()
    if engine is None:
        raise TexError("No LaTeX engine found. Install tectonic (recommended) or MacTeX/TeX Live.")
    runs = 2 if engine.name == "pdflatex" else 1
    log = ""
    for _ in range(runs):
        r = subprocess.run(engine.command(tex, outdir), cwd=tex.parent, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        log = r.stdout + "\n" + r.stderr
        logf = outdir / (tex.stem + ".log")
        if logf.exists():
            log = logf.read_text(errors="replace") + "\n" + log
        if r.returncode != 0:
            raise TexError(f"LaTeX failed: {first_error(log)}", log)
    pdf = outdir / (tex.stem + ".pdf")
    if not pdf.exists():
        raise TexError("LaTeX finished but no PDF was produced.", log)
    return pdf


def page_count(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)
