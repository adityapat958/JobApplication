"""PDF source for `jobapp resume import` (fake resume compiled from LaTeX; no personal data)."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobapp.cli import app
from jobapp.resume import docx_import as di
from jobapp.resume import pdf_extract as px
from jobapp.resume import tex as texmod
from pdf_factory import compile_tex, simple_resume_pdf

FIX = Path(__file__).parent / "fixtures" / "docx_import"
CORRECT = (FIX / "correct.tex").read_text()
needs_tex = pytest.mark.skipif(texmod.detect() is None, reason="no LaTeX engine")
URLS = {"mailto:sam@example.com", "https://www.linkedin.com/in/sample", "https://example.com/dash"}
runner = CliRunner()


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    if texmod.detect() is None:
        pytest.skip("no LaTeX engine")
    return simple_resume_pdf(tmp_path_factory.mktemp("src") / "Sam Resume.pdf")


@needs_tex
def test_extract_pdf(pdf):
    ex = di.extract(pdf)
    assert ex.kind == "pdf" and ex.pages == 1 and ex.urls == URLS
    md = ex.markdown
    assert "## EDUCATION" in md and "## EXPERIENCE" in md
    assert "- Built a valuation model for 12 Nordic utilities" in md
    assert "[demo](https://example.com/dash)" in md and "[LinkedIn](https://www.linkedin.com/in/sample)" in md
    assert "Example Business School ⇥ Aug 2024 – June 2026" in md
    assert ex.layout["source_format"] == "pdf" and "not recoverable" in ex.layout["note"].lower()
    assert ex.layout["section_order"] == ["EDUCATION", "SKILLS", "EXPERIENCE", "PROJECTS"]
    assert ex.layout["page_size_in"][0] > 8
    assert "•" not in ex.plain  # bullet glyphs stripped from the diff text


@needs_tex
def test_links_have_anchor_text(pdf):
    got = {lk["url"]: lk["text"] for lk in px.links(pdf)}
    assert got == {"mailto:sam@example.com": "sam@example.com",
                   "https://www.linkedin.com/in/sample": "LinkedIn", "https://example.com/dash": "demo"}


@needs_tex
def test_extract_pdf_without_pdftotext(pdf, monkeypatch):
    monkeypatch.setattr(px, "which", lambda name: None)
    ex = di.extract(pdf)
    assert ex.urls == URLS and ex.pages == 1 and ex.layout["text_extractor"] == "pypdf"
    assert "Fjord Capital" in ex.markdown and "valuation" in ex.plain


def test_extract_rejects_bad_pdf(tmp_path):
    bad = tmp_path / "r.pdf"
    bad.write_text("not a pdf")
    with pytest.raises(di.ImportError_) as e:
        di.extract(bad)
    assert "PDF" in str(e.value)
    with pytest.raises(di.ImportError_) as e:
        di.extract(tmp_path / "x.doc")


@needs_tex
def test_scanned_pdf_rejected(tmp_path):
    scan = compile_tex(r"\documentclass{article}\pagestyle{empty}\begin{document}\rule{3cm}{3cm}\end{document}",
                       tmp_path / "scan.pdf")
    with pytest.raises(di.ImportError_) as e:
        di.extract(scan)
    assert "scan" in str(e.value)


@needs_tex
def test_prepare_pdf_prompt(profile, pdf):
    p = di.prepare(pdf)
    text = p.read_text()
    assert "{{" not in text and "PDF file" in text and "source_format: pdf" in text
    assert "[demo](https://example.com/dash)" in text and "target_pages: 1" in text
    assert (profile / "import" / "source.pdf").exists() and not (profile / "import" / "source.docx").exists()
    meta = json.loads((profile / "import" / "meta.json").read_text())
    assert meta["kind"] == "pdf" and set(meta["urls"]) == URLS


def test_prompt_rules_generic_and_kept():
    raw = (Path(__file__).parents[1] / "prompts" / "docx_to_latex.md").read_text()
    for rule in ("verbatim", "section order", "\\href{url}{text}", "SKILLS-CORE", "SKILLS-TECH-END",
                 "font 9.5–11pt", "margins 0.3–0.75in", "Never use `tabular`", "mapping_notes",
                 "Don't define new macros", "Never fix length by changing the content", "{{FIX_REPORT}}"):
        assert rule in raw, rule
    assert "{{DOCX_" not in raw and "{{SOURCE_MARKDOWN}}" in raw and "{{SOURCE_KIND}}" in raw


# ── token diff: ligatures, bullets, separators, hyphenation ──
def test_ligatures_bullets_separators():
    src = "• Oﬃce eﬃcient ﬁnance | ﬂow\n§ Second bullet\no Sub bullet · item"
    out = "Office efficient finance flow Second bullet Sub bullet item"
    assert di.content_diff(px.strip_bullets(src), out) == ([], [])


def test_hyphenation_only_for_that_split():
    src = "Built a valuation model for utilities"
    assert di.content_diff(src, "Built a valu-\nation model for utilities") == ([], [])
    assert di.content_diff("Built a valu-\nation model", "Built a valuation model") == ([], [])
    # a compound split at its own hyphen is fine on both sides
    assert di.content_diff("real-time data", "real-\ntime data") == ([], [])
    # but words glued or split elsewhere are still reported
    assert di.content_diff(src, "Built a valu ation model for utilities") == (["valuation"], ["ation", "valu"])
    assert di.content_diff("real time", "realtime") == (["real", "time"], ["realtime"])


@needs_tex
def test_verify_pdf_source_passes(profile, pdf):
    di.prepare(pdf)
    di.candidate_path().write_text(CORRECT)
    rep = di.verify()
    assert rep.ok, rep.summary()
    assert "Same words as the PDF file" in rep.summary()
    assert di.accept().read_text() == CORRECT


@needs_tex
def test_verify_pdf_source_reworded_fails(profile, pdf):
    di.prepare(pdf)
    reworded = CORRECT.replace("Built a valuation model for 12 Nordic utilities",
                               "Developed a valuation model for twelve Nordic utilities") \
                      .replace("https://example.com/dash", "https://example.com/other")
    di.candidate_path().write_text(reworded)
    rep = di.verify()
    assert not rep.ok
    assert rep.missing == ["12", "built"] and rep.extra == ["developed", "twelve"]
    gates = {g.name: g for g in rep.gates}
    assert not gates["Same words as the PDF file"].ok and not gates["Links"].ok
    report = di.fix_report_path().read_text()
    assert '"developed"' in report and "https://example.com/dash" in report


@needs_tex
def test_verify_pdf_page_count(profile, pdf):
    di.prepare(pdf)
    di.candidate_path().write_text(CORRECT.replace(r"\end{document}", r"\newpage\mbox{}\end{document}"))
    rep = di.verify()
    g = {g.name: g for g in rep.gates}["Page count"]
    assert not g.ok and "2 page(s), target 1" in g.detail


@needs_tex
def test_cli_pdf_flow(profile, pdf):
    r = runner.invoke(app, ["resume", "import", str(pdf), "--prepare"])
    assert r.exit_code == 0 and "prompt.md" in r.output
    di.candidate_path().write_text(CORRECT)
    r = runner.invoke(app, ["resume", "import", "--accept"])
    assert r.exit_code == 0, r.output


def test_cli_help_mentions_pdf():
    r = runner.invoke(app, ["resume", "import", "--help"])
    assert "PDF" in r.output


@needs_tex
def test_api_mode_pdf(profile, pdf):
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return "```latex\n" + CORRECT + "```"
    rep = di.run_api(pdf, call=fake)
    assert rep.ok and len(prompts) == 1 and "source_format: pdf" in prompts[0]


@needs_tex
def test_line_end_hyphens_in_built_pdf(tmp_path):
    """pdftotext's default mode glues 'fail-' + 'closed' into 'failclosed'; the gate must not."""
    tex = (r"\documentclass{article}\pagestyle{empty}\usepackage[T1]{fontenc}\begin{document}"
           r"\noindent fail-\\closed mint and end-to-\\end runs with a valu-\\ation model\end{document}")
    pdf = compile_tex(tex, tmp_path / "h.pdf")
    src = "fail-closed mint and end-to-end runs with a valuation model"
    assert di.content_diff(src, di.pdf_text(pdf)) == ([], [])
    assert di.content_diff("fail closed mint and end to end runs with a valuation model",
                           di.pdf_text(pdf)) == ([], [])  # hyphens are separators on both sides
    assert di.content_diff(src.replace("valuation", "pricing"), di.pdf_text(pdf))[0] == ["pricing"]
