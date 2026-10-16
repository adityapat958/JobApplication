import re
import shutil

import pytest

from jobapp import config, paths
from jobapp.resume import tex as texmod
from jobapp.resume.build import CORE, TECH, check_markers, choose, outside_markers, parse_items, read_block, tailor
from jobapp.resume.keywords import Bank
from jobapp.resume.service import BuildError, build_pdf, output_name, slug_part

EX_TEX = (paths.examples_profile() / "resume" / "resume.tex").read_text()
EX_BANK = Bank.load(paths.examples_profile() / "resume" / "keywords.yaml")
HAVE_TEX = texmod.detect() is not None

# A resume shaped like real ones: comments inside the Skills block, CRLF-free, extra content after.
COMMENTY = r"""\documentclass{article}
\begin{document}
% intro comment, keep me
\begin{itemize}
    % <<SKILLS-CORE>>
    \item {\small\textbf{Core Competencies:}
        Data Analysis, Financial Modelling,
        Valuation}
    % <<SKILLS-CORE-END>>
%between markers comment
    % <<SKILLS-TECH>>
    \item {\small\textbf{Technical Skills:}
        Python, C++, %MATLAB
        SQL,
        %HuggingFace,
        Excel}
    \item {\small\textbf{Languages:} English, Norwegian}
    % <<SKILLS-TECH-END>>
\end{itemize}
Tail text with 50\% and R\&D.
\end{document}
"""


def test_markers_ok_and_errors():
    check_markers(EX_TEX)
    with pytest.raises(ValueError):
        check_markers(EX_TEX.replace(CORE[0], "% nothing"))
    with pytest.raises(ValueError):
        check_markers(EX_TEX + "\n" + CORE[0] + "\n" + CORE[1] + "\n")
    with pytest.raises(ValueError):
        check_markers(EX_TEX.replace(TECH[1], ""))


def test_parse_items_strips_comments():
    b = read_block(COMMENTY, TECH)
    assert b.items == ["Python", "C++", "SQL", "Excel"]
    assert b.label == "Technical Skills:"


def test_choose_budget():
    out = choose(["SQL", "Tableau"], ["Excel", "Word"], ["Excel", "Word", "SQL", "Tableau", "SAP"], budget=20)
    assert out[:2] == ["SQL", "Tableau"]
    assert len(", ".join(out)) <= 21


@pytest.mark.parametrize("tex", [EX_TEX, COMMENTY], ids=["example", "commenty"])
def test_byte_identity_outside_markers(tex):
    t = tailor(tex, EX_BANK, ["Budgeting and Forecasting", "Due Diligence"], ["Tableau", "Jira"])
    assert t.tex != tex
    assert outside_markers(t.tex) == outside_markers(tex)
    # and literally: prefix up to the first marker content and suffix after the last are identical
    first = tex.index(CORE[0])
    assert t.tex[:first] == tex[:first]
    last = tex.rindex(TECH[1])
    assert t.tex[t.tex.rindex(TECH[1]):] == tex[last:]
    assert t.core[0] == "Budgeting and Forecasting" and t.tech[0] == "Tableau"
    check_markers(t.tex)


def test_extra_items_in_tech_block_untouched():
    t = tailor(COMMENTY, EX_BANK, [], ["Power BI"])
    assert r"\item {\small\textbf{Languages:} English, Norwegian}" in t.tex
    assert "%MATLAB" not in t.tex.split(TECH[0])[1].split(r"\item {\small\textbf{Languages:}")[0]


def test_escaping():
    bank = Bank.from_dict({"core_competencies": {"a": ["M&A", "P&L Ownership"]}, "technical_skills": ["C#"]})
    t = tailor(COMMENTY, bank, ["M&A"], ["C#"])
    assert r"M\&A" in t.tex and r"C\#" in t.tex


def test_core_only_resume():
    tex = COMMENTY.replace(TECH[0], "% x").replace(TECH[1], "% y")
    t = tailor(tex, EX_BANK, ["Valuation"], ["Tableau"])
    assert "Tableau" in t.core


def test_output_name():
    cfg = config.parse({"profile": {"name": "Ola Nordmann"}})
    assert output_name(cfg, "Equinor ASA", "Økonomi-analytiker (Trainee)") == "Ola_Nordmann_Equinor-ASA_Okonomi-analytiker"
    cfg = config.parse({"profile": {"name": "Cher"}})
    assert output_name(cfg, "DNB", "Analyst") == "Cher_DNB_Analyst"
    assert slug_part("Café / Søren & Co.") == "Cafe-Soren-Co"


def test_build_errors_are_friendly(profile):
    cfg = config.load()
    (profile / "resume" / "resume.tex").unlink()
    with pytest.raises(BuildError) as e:
        build_pdf(cfg, company="X", role="Y", description="Excel")
    assert "wasn't found" in str(e.value)


@pytest.mark.skipif(not HAVE_TEX, reason="no LaTeX engine")
def test_build_pdf_example(profile):
    cfg = config.load()
    res = build_pdf(cfg, company="Equinor", role="Business Analyst",
                    description="We want Excel, Tableau, SQL, forecasting and stakeholder management.")
    assert res.pdf.exists() and res.pdf.name == "Alex_Example_Equinor_Business-Analyst.pdf"
    assert res.pages == 1 and not [w for w in res.warnings if "page" in w]
    assert "Tableau" in res.tech and "Budgeting and Forecasting" in res.core
    from pypdf import PdfReader
    txt = PdfReader(str(res.pdf)).pages[0].extract_text()
    assert "Tableau" in txt and "Northwind Consulting" in txt


def test_no_repeats_from_other_skills_lines():
    tex = "\n".join([
        r"\begin{itemize}",
        r"    \item {\small\textbf{Languages:} Python, Go}",
        "% <<SKILLS-TECH>>",
        r"    \item {\small\textbf{Cloud:} AWS (ECS, IAM), Docker}",
        "% <<SKILLS-TECH-END>>",
        "% <<SKILLS-CORE>>",
        r"    \item {\small\textbf{Systems:} Distributed Systems, Observability}",
        "% <<SKILLS-CORE-END>>",
        r"\end{itemize}", ""])
    bank = Bank(core=["Distributed Systems", "Observability", "SRE"],
                tech=["AWS", "Docker", "Python", "Kubernetes", "Terraform"])
    t = tailor(tex, bank, [], ["Python", "Kubernetes"])
    assert "Python" not in t.tech and "Kubernetes" in t.tech  # Python is already on the Languages line
    assert parse_items("AWS (ECS, IAM), Docker") == ["AWS (ECS, IAM)", "Docker"]
    assert all(i.count("(") == i.count(")") for i in t.tech)
    assert outside_markers(t.tex) == outside_markers(tex)


def test_choose_keeps_users_detailed_item():
    out = choose(["AWS", "Kubernetes"], ["AWS (ECS, IAM)", "Docker"], ["AWS", "ECS", "Docker", "Kubernetes"], budget=50)
    assert out == ["AWS (ECS, IAM)", "Kubernetes", "Docker"]


def test_keyword_lines_not_hyphenated():
    bank = Bank.from_dict({"core_competencies": ["internationalization", "telecommunications"],
                           "technical_skills": ["Excel"]})
    t = tailor(COMMENTY, bank, ["internationalization", "telecommunications"], ["Excel"])
    assert t.tex.count(r"\item {\language=255 \small\textbf{") == 2
    check_markers(t.tex)
    again = tailor(t.tex, bank, ["telecommunications"], [])  # re-tailoring doesn't stack the switch
    assert r"\language=255 \language=255" not in again.tex
