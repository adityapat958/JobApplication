"""`missing` = skills-vocabulary terms in the ad that aren't in the keyword bank (no names, no boilerplate)."""
import pytest

from jobapp.resume.keywords import Bank, BankError
from jobapp.resume.matching import Matcher, clean_jd, find_missing, score
from jobapp.resume.vocab import Vocab, default
from jobapp.text import strip_boilerplate

BANK = Bank.from_dict({
    "core_competencies": {"a": ["Computer Vision", "Object Detection and Tracking", "Machine Learning"]},
    "technical_skills": {"t": ["Python", "PyTorch", "Excel", "SQL"]},
})

LINKEDIN_JD = """About the job
We are building perception for warehouse robots. You will train object detection models in PyTorch
and deploy them with TensorRT on NVIDIA Jetson. Experience with ROS2 and Kubernetes is a plus.
Strong Python and C++ required.

Meet the hiring team
Brianna Okafor-Lindqvist
Brianna Okafor-Lindqvist
2nd
Senior Technical Recruiter at Example Robotics
Job poster
Message
Desmond Achterberg
Engineering Manager, Perception
Message

Seniority level
Entry level
Employment type
Full-time
Job function
Engineering and Information Technology
Industries
Robotics Engineering
Referrals increase your chances of interviewing at Example Robotics by 2x
See who you know
Get notified about new Perception Engineer jobs in Boston, MA.
Sign in to create job alert
"""

EEO_JD = """Responsibilities
• Build data pipelines in Apache Airflow and dbt
• Model data in Snowflake

What we offer
• Competitive Salary and Equity Package
• Comprehensive Medical, Dental and Vision Insurance
• Flexible Paid Time Off Policy and Wellness Stipend

Example Corp is an Equal Opportunity Employer. All qualified applicants will receive consideration for employment
without regard to race, color, religion, sex, sexual orientation, gender identity, national origin, disability or
protected veteran status. We participate in E-Verify. Reasonable Accommodation: contact Talent Acquisition Partners.
Pay Transparency: the base salary range for this role is $120,000 - $150,000. Visit https://example.invalid/careers
"""

NO_JD = """Om stillingen
Vi søker en analytiker til vårt team i Oslo. Du vil jobbe med dataanalyse, rapportering i Power BI og
budsjettering. Erfaring med SQL og maskinlæring er en fordel. Kjennskap til SAP er ønskelig.

Kvalifikasjoner
• Mastergrad i økonomi eller tilsvarende
• God forståelse av regnskap og IFRS
• Flytende norsk og engelsk

Vi tilbyr
• Konkurransedyktig lønn og gode pensjonsordninger
• Fleksibel arbeidstid, treningsrom og Sosiale Arrangementer
• Et Inkluderende Arbeidsmiljø med Faglig Utvikling

Om oss
Eksempel Kraft AS er Nordens Ledende Energiselskap med Bærekraft i Fokus og 4000 ansatte.

Kontaktperson
Ingrid Haugeland-Sæther, Avdelingsleder Analyse
Tlf: 41 23 45 67
ingrid.haugeland@example.no
"""

PEOPLE = ["Brianna", "Okafor", "Lindqvist", "Desmond", "Achterberg", "Ingrid", "Haugeland", "Sæther"]


def _flat(xs):
    return " ".join(xs)


def test_linkedin_hiring_team_names_not_missing():
    r = score(LINKEDIN_JD, BANK, ("Example Robotics", "Boston, MA"))
    for p in PEOPLE:
        assert p not in _flat(r.missing + r.matched), r.missing
    assert {"TensorRT", "ROS2", "Kubernetes", "C++"} <= set(r.missing)
    assert "Object Detection" not in r.missing  # covered by "Object Detection and Tracking"
    assert {"Python", "PyTorch"} <= set(r.matched)
    for junk in ("Seniority", "Employment Type", "Job Function", "Referrals", "Message", "Entry"):
        assert junk not in _flat(r.missing)


def test_eeo_and_benefits_boilerplate_not_missing():
    r = score(EEO_JD, BANK, ("Example Corp", ""))
    assert set(r.missing) == {"Apache Airflow", "dbt", "Snowflake", "Data Pipelines"}, r.missing
    out = strip_boilerplate(EEO_JD)
    assert "Equal Opportunity" not in out and "Dental" not in out and "example.invalid" not in out
    assert "Snowflake" in out


def test_norwegian_ad():
    bank = Bank.from_dict({"core_competencies": {"a": ["Data Analysis", "Budgeting"]},
                           "technical_skills": {"t": ["Excel", "Power BI"]}})
    r = score(NO_JD, bank, ("Eksempel Kraft AS", "Oslo"))
    # Norwegian words map to English skill names; the bank's own terms count as matched (vocab aliases)
    assert {"Data Analysis", "Budgeting", "Power BI"} <= set(r.matched)
    assert {"SQL", "Machine Learning", "SAP", "Accounting", "IFRS", "Norwegian", "English"} <= set(r.missing), r.missing
    joined = _flat(r.missing)
    for p in PEOPLE + ["Sosiale", "Arbeidsmiljø", "Nordens", "Bærekraft", "Sustainability", "Konkurransedyktig"]:
        assert p not in joined, r.missing


def test_missing_only_from_vocab():
    jd = "Join the Moonshot Squad! Our Hyper Growth Culture rewards Bold Ideas. Must know Rust and Terraform."
    assert find_missing(jd, BANK) == ["Rust", "Terraform"]


def test_case_sensitive_terms():
    assert find_missing("You will spark curiosity and react quickly; excel at swift delivery.", BANK) == []
    assert find_missing("Our stack: React, Swift and Apache Spark.", BANK) == ["Apache Spark", "React", "Swift"]


def test_ignore_company_and_bank_variants():
    b = Bank.from_dict({"technical_skills": {"t": ["Kubernetes (k8s)"]}})
    assert find_missing("We run k8s and Snowflake.", b, ("Snowflake Inc",)) == ["Snowflake"]
    assert find_missing("We run k8s and Snowflake.", b, ("Snowflake",)) == []


def test_extra_vocab_from_keywords_yaml():
    b = Bank.from_dict({"technical_skills": {"t": ["Python"]},
                        "extra_vocab": {"mine": {"Isaac ROS": ["isaac-ros"], "Kubernetes": ["kube cluster"]}}})
    r = score("Experience with isaac-ros and a kube cluster.", b)
    assert r.missing == ["Isaac ROS", "Kubernetes"]
    b2 = Bank.from_dict({"technical_skills": ["Python"], "extra_vocab": ["Foxglove"]})
    assert find_missing("Foxglove dashboards", b2) == ["Dashboards", "Foxglove"]
    with pytest.raises(BankError):
        Bank.from_dict({"technical_skills": ["Python"], "extra_vocab": "Foxglove"})
    # the shipped vocabulary is not changed by a user's extra_vocab
    assert all(a.text != "kube cluster" for t in default().terms for a in t.forms)


def test_vocab_is_sane():
    v = default()
    names = [t.name for t in v.terms]
    assert len(names) >= 300
    assert len({n.casefold() for n in names}) == len(names), "duplicate vocabulary terms"
    norsk = {f.text for t in v.terms for f in t.forms} & {"maskinlæring", "regnskap", "prosjektledelse", "dataanalyse"}
    assert len(norsk) == 4


def test_contact_please_contact_block():
    jd = ("Requirements\n• SQL and Tableau\n\nIf you have any questions, please contact:\n\nHiring manager\n"
          "Torvald Eksempelsen\nTorvald.Eksempelsen@example.com\n(Norway +47) 900 00 000\n\nRecruiter\n"
          "Sunniva Prøvesen\nSunniva.Provesen@example.com\n")
    out = clean_jd(jd)
    assert "Torvald" not in out and "Sunniva" not in out and "example.com" not in out
    assert "Tableau" in out


def test_boilerplate_section_ends_at_next_heading():
    jd = "About us\nWe are a Great Place.\n\nRequirements\n• Python and Docker\n"
    out = strip_boilerplate(jd)
    assert "Great Place" not in out and "Docker" in out
    # an "About us" with no following heading drops at most two paragraphs
    jd2 = "About us\nP1 Great.\n\nP2 Also.\n\nYou will use Terraform daily."
    assert "Terraform" in strip_boilerplate(jd2)


def test_matcher_vocab_cached_per_bank():
    m = Matcher(BANK)
    r1 = m.score_job({"description": "Rust and SQL", "title": "Engineer"})
    assert r1.missing == ["Rust"] and r1.matched == ["SQL"]
    assert isinstance(m.vocab, Vocab)
