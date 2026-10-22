import subprocess
from pathlib import Path
import pytest
from jobapp import paths
from jobapp.resume import tex as texmod


def test_inserted_once_before_begin_document():
    src = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    out = texmod.keep_headings(src)
    assert out.index("needspace") < out.index("\\begin{document}")
    assert texmod.keep_headings(out) == out
    assert texmod.keep_headings("no document here") == "no document here"


def _lines_after_break(pdf: Path) -> list[str]:
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    pages = [p.strip().splitlines() for p in txt.split("\f") if p.strip()]
    return pages


def _doc(n: int, patched: bool) -> str:
    filler = "\n".join(f"Line {i} of filler text." + "\\\\" for i in range(n))
    src = ("\\documentclass{article}\\usepackage[margin=1in]{geometry}\\pagestyle{empty}\n"
           "\\newcommand{\\expentry}[3]{\\noindent\\textbf{#1} \\hfill #2\\\\ \\textit{#3}\\par}\n"
           "\\begin{document}\n\\noindent " + filler + "\n\n\\expentry{ORPHANCO}{2023}{Analyst}\n"
           "\\begin{itemize}\\item first bullet\\item second bullet\\end{itemize}\n\\end{document}\n")
    return texmod.keep_headings(src) if patched else src


def _pages(tmp_path, src):
    f = tmp_path / "r.tex"; f.write_text(src)
    return _lines_after_break(texmod.compile_pdf(f, tmp_path, texmod.detect()))


@pytest.mark.skipif(texmod.detect() is None, reason="no TeX engine")
def test_heading_moves_to_next_page(tmp_path):
    # find a filler length where, WITHOUT the patch, the heading is stranded at the bottom of page 1
    for n in range(30, 70):
        p = _pages(tmp_path, _doc(n, False))
        if len(p) == 2 and any("ORPHANCO" in l for l in p[0]) and not any("first bullet" in l for l in p[0]):
            break
    else:
        pytest.skip("could not construct an orphaned heading with this TeX engine")
    p = _pages(tmp_path, _doc(n, True))
    assert not any("ORPHANCO" in l for l in p[0])
    assert any("ORPHANCO" in l for l in p[1]) and any("first bullet" in l for l in p[1])
