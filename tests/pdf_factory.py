"""Build fake PDF resumes by compiling a tiny LaTeX file (no personal data).

The look deliberately differs from the import template (• bullets, | separators, ragged layout) —
like a resume exported from Word/Google Docs — but the words and links match
fixtures/docx_import/correct.tex.
"""
import shutil
import subprocess
from pathlib import Path

SOURCE_TEX = r"""\documentclass[11pt]{article}
\usepackage[margin=0.8in]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\begin{document}
\begin{center}
{\Large Sam Sample}\\
Finance Student | Oslo, Norway\\
\href{mailto:sam@example.com}{sam@example.com} | \href{https://www.linkedin.com/in/sample/}{LinkedIn}
\end{center}

\textbf{EDUCATION}\par\medskip
Example Business School \hfill Aug 2024 – June 2026\\
MSc in Finance, GPA 4.8/5.0\par\bigskip

\textbf{SKILLS}\par\medskip
Core Competencies: Financial Analysis, Valuation, Market Research\\
Technical Skills: Excel, SQL, Power BI\par\bigskip

\textbf{EXPERIENCE}\par\medskip
Fjord Capital \hfill June 2025 – Aug 2025\\
Summer Analyst\\
\hspace*{1em}• Built a valuation model for 12 Nordic utilities\\
\hspace*{1em}• Presented findings to the investment committee\par\bigskip

\textbf{PROJECTS}\par\medskip
Housing Dashboard – \href{https://example.com/dash}{demo}\\
\hspace*{1em}• Tracked rental prices across 15 districts
\end{document}
"""


def compile_tex(tex: str, path: Path) -> Path:
    path = Path(path)
    work = path.parent / (path.stem + "_build")
    work.mkdir(parents=True, exist_ok=True)
    (work / "src.tex").write_text(tex, encoding="utf-8")
    exe = shutil.which("pdflatex")
    if exe:
        cmd = [exe, "-interaction=nonstopmode", "-halt-on-error", "src.tex"]
    else:
        cmd = [shutil.which("tectonic"), "src.tex"]
    subprocess.run(cmd, cwd=work, capture_output=True, check=True, timeout=120)
    shutil.copy2(work / "src.pdf", path)
    return path


def simple_resume_pdf(path: Path) -> Path:
    return compile_tex(SOURCE_TEX, path)
