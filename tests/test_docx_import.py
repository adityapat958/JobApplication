import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docx_factory import simple_resume
from jobapp.cli import app
from jobapp.resume import docx_import as di
from jobapp.resume import tex as texmod

FIX = Path(__file__).parent / "fixtures" / "docx_import"
CORRECT = (FIX / "correct.tex").read_text()
HAVE_TEX = texmod.detect() is not None
needs_tex = pytest.mark.skipif(not HAVE_TEX, reason="no LaTeX engine")
runner = CliRunner()


@pytest.fixture
def docx(tmp_path):
    return simple_resume(tmp_path / "Sam Resume.docx")


def test_extract(docx):
    ex = di.extract(docx)
    assert ex.pages == 1
    assert ex.urls == {"mailto:sam@example.com", "https://www.linkedin.com/in/sample", "https://example.com/dash"}
    assert ex.layout["section_order"] == ["Education", "Skills", "Experience", "Projects"]
    assert ex.layout["margins_in"]["left"] == 0.7 and ex.layout["base_font_pt"] == 10.5
    assert "Fjord Capital" in ex.plain and "Fjord Capital" in ex.markdown


def test_fallback_without_pandoc(docx, monkeypatch):
    monkeypatch.setattr(di, "which", lambda name: None)
    ex = di.extract(docx)
    assert not ex.used_pandoc
    assert "[LinkedIn](https://www.linkedin.com/in/sample)" in ex.markdown
    assert "**Fjord Capital**" in ex.markdown and "# Education" in ex.markdown
    assert "- Built a valuation model" in ex.markdown


def test_extract_rejects_non_docx(tmp_path):
    bad = tmp_path / "r.docx"
    bad.write_text("not a zip")
    with pytest.raises(di.ImportError_):
        di.extract(bad)
    with pytest.raises(di.ImportError_):
        di.extract(tmp_path / "x.pdf")


def test_pages_from_app_xml(tmp_path, docx):
    import zipfile
    out = tmp_path / "two.docx"
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/app.xml":
                data = re.sub(rb"<Pages>\d+</Pages>", b"", data).replace(b"</Properties>", b"<Pages>2</Pages></Properties>")
            zout.writestr(item, data)
    assert di.docx_pages(out) == 2


def test_prepare_renders_prompt(profile, docx):
    p = di.prepare(docx)
    text = p.read_text()
    assert "## SYSTEM" in text and "Fjord Capital" in text and r"\expentry" in text
    assert "{{" not in text  # all slots filled
    assert "target_pages: 1" in text
    assert str(di.candidate_path()) in text
    assert "Verification gates" not in text and "<!--" not in text
    meta = json.loads((profile / "import" / "meta.json").read_text())
    assert meta["target_pages"] == 1 and len(meta["urls"]) == 3


def test_tex_urls():
    assert di.tex_urls(CORRECT) == {"mailto:sam@example.com", "https://www.linkedin.com/in/sample",
                                    "https://example.com/dash"}
    assert di.tex_urls(r"\projentry{X}%" + "\n" + r"    {https://a.example/x}%" + "\n{Py}") == {"https://a.example/x"}


def test_token_normalisation():
    a = di.normalize_tokens("Aug 2024 – June 2026 · GPA 4.8/5.0 ﬁnance  Økonomi")
    b = di.normalize_tokens("aug 2024 -- june 2026 gpa 4 8 5 0 finance økonomi")
    assert a == b
    assert di.normalize_tokens("valu-\nation") == di.normalize_tokens("valuation")


@needs_tex
def test_verify_correct_passes(profile, docx):
    di.prepare(docx)
    di.candidate_path().write_text(CORRECT)
    rep = di.verify()
    assert rep.ok, rep.summary()
    assert not di.fix_report_path().exists()
    dst = di.accept()
    assert dst.read_text() == CORRECT
    assert list(dst.parent.glob("resume.tex.bak-*"))  # old resume backed up


@needs_tex
def test_verify_reworded_fails_with_tokens(profile, docx):
    di.prepare(docx)
    reworded = CORRECT.replace("Built a valuation model for 12 Nordic utilities",
                               "Developed a valuation model for twelve Nordic utilities")
    di.candidate_path().write_text("Here you go:\n```latex\n" + reworded + "\n```\n")
    rep = di.verify()
    assert not rep.ok
    assert rep.missing == ["12", "built"] and rep.extra == ["developed", "twelve"]
    report = di.fix_report_path().read_text()
    assert '"built"' in report and '"developed"' in report and "Fix ONLY" in report
    assert di.candidate_path().read_text().startswith(r"\documentclass")  # fences stripped
    with pytest.raises(di.ImportError_):
        di.accept()


@needs_tex
def test_verify_detects_link_page_marker_problems(profile, docx):
    di.prepare(docx)
    bad = CORRECT.replace("https://example.com/dash", "https://example.com/other") \
                 .replace("% <<SKILLS-TECH-END>>", "")
    bad = bad.replace(r"\end{document}", r"\newpage x \end{document}")
    di.candidate_path().write_text(bad)
    rep = di.verify()
    names = {g.name: g for g in rep.gates}
    assert not names["Links"].ok and "https://example.com/dash" in names["Links"].detail
    assert not names["Page count"].ok
    assert not names["Skills markers"].ok
    assert rep.extra == ["x"]


@needs_tex
def test_verify_compile_error(profile, docx):
    di.prepare(docx)
    di.candidate_path().write_text(CORRECT.replace(r"\section{Skills}", r"\section{Skills_}"))
    rep = di.verify()
    g = rep.gates[0]
    assert g.name == "Compiles" and not g.ok and "Missing $" in g.detail


@needs_tex
def test_rounds_counted(profile, docx):
    di.prepare(docx)
    di.candidate_path().write_text(CORRECT.replace("Valuation,", "Valuations,"))
    for i in range(3):
        rep = di.verify()
    assert rep.round == 3 and "Still failing" in rep.summary()


@needs_tex
def test_api_mode_loop(profile, docx):
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "```latex\n" + CORRECT.replace("Valuation,", "Valuations,") + "```\n```yaml\nmapping_notes: {}\n```"
        return "```latex\n" + CORRECT + "```"
    rep = di.run_api(docx, call=fake)
    assert rep.ok and len(prompts) == 2
    assert "Previous attempt failed" in prompts[1] and '"valuation"' in prompts[1]
    assert (profile / "import" / "mapping_notes.yaml").exists()


def test_api_mode_without_key(profile, docx, monkeypatch):
    monkeypatch.setattr(di, "api_caller", lambda: None)
    with pytest.raises(di.ImportError_) as e:
        di.run_api(docx)
    assert "--prepare" in str(e.value)


@needs_tex
def test_cli_agent_flow(profile, docx):
    r = runner.invoke(app, ["resume", "import", str(docx), "--prepare"])
    assert r.exit_code == 0 and "prompt.md" in r.output
    di.candidate_path().write_text(CORRECT.replace("12 Nordic", "twelve Nordic"))
    r = runner.invoke(app, ["resume", "import", "--verify"])
    assert r.exit_code == 1 and "fix_report.md" in r.output.replace("\n", "")
    di.candidate_path().write_text(CORRECT)
    r = runner.invoke(app, ["resume", "import", "--accept"])
    assert r.exit_code == 0 and "resume.tex" in r.output
