"""Resume variants: config, per-job pick (override → prefer_if on title → JD → default), scoring, build, UI."""
import json
import shutil

import pytest
import yaml

from jobapp import config as config_mod
from jobapp import db, paths
from jobapp.models import JobPosting
from jobapp.resume.variants import auto_pick, pick, validate_choice

VARIANTS = {
    "perception": {"tex": "resume/perception.tex", "keywords": "resume/kw_perception.yaml",
                   "prefer_if": ["perception", "vision", "slam", "robot*", "autonom*"]},
    "mle": {"tex": "resume/mle.tex", "keywords": "resume/kw_mle.yaml",
            "prefer_if": ["machine learning", "ml", "llm", "genai", "data scientist"]},
}


@pytest.fixture
def vprofile(profile):
    """The example profile with two resume variants (same template, different keyword banks)."""
    r = profile / "resume"
    shutil.copy(r / "resume.tex", r / "perception.tex")
    shutil.copy(r / "resume.tex", r / "mle.tex")
    (r / "kw_perception.yaml").write_text(yaml.safe_dump({
        "core_competencies": {"v": ["Computer Vision", "SLAM", "Sensor Fusion"]},
        "technical_skills": {"t": ["C++", "ROS", "OpenCV"]}}))
    (r / "kw_mle.yaml").write_text(yaml.safe_dump({
        "core_competencies": {"m": ["Large Language Models", "Machine Learning", "Recommender Systems"]},
        "technical_skills": {"t": ["Python", "PyTorch", "Kubernetes"]}}))
    data = yaml.safe_load(paths.config_path().read_text())
    data["resume"]["variants"] = VARIANTS
    data["resume"]["default_variant"] = "perception"
    paths.config_path().write_text(yaml.safe_dump(data, sort_keys=False))
    return profile


def _cfg(**resume):
    return config_mod.parse({"resume": {"variants": VARIANTS, **resume}})


def test_config_default_and_errors():
    assert _cfg().resume.default_variant == "perception"  # first one when not given
    assert _cfg(default_variant="mle").resume.default_variant == "mle"
    with pytest.raises(config_mod.ConfigError) as e:
        _cfg(default_variant="mel")
    assert "did you mean 'mle'" in str(e.value)
    with pytest.raises(config_mod.ConfigError):
        config_mod.parse({"resume": {"default_variant": "x"}})
    with pytest.raises(config_mod.ConfigError):
        config_mod.parse({"resume": {"variants": {"bad name!": {"tex": "a.tex"}}}})
    single = config_mod.parse({})
    assert single.resume.variants == {} and pick(single, {"title": "ML Engineer"}) is None


@pytest.mark.parametrize("title,desc,want", [
    ("Perception Engineer", "", "perception"),
    ("Machine Learning Engineer", "", "mle"),
    ("Robotics Software Engineer Intern", "", "perception"),
    ("Software Engineer", "We build LLM agents and GenAI products. LLM serving.", "mle"),
    ("Software Engineer", "SLAM and vision on autonomous robots", "perception"),
    ("Software Engineer", "Backend Go services", "perception"),               # nothing → default
    ("ML Engineer, Perception", "", "perception"),                            # tie on title → default wins
    ("ML Engineer, Perception", "LLM, LLM, machine learning, ML", "mle"),     # tie broken by the JD
])
def test_auto_pick(title, desc, want):
    assert auto_pick(_cfg(), {"title": title, "description": desc}) == want


def test_override_wins_and_validation():
    cfg = _cfg()
    assert pick(cfg, {"title": "Perception Engineer", "variant": "mle"}) == "mle"
    assert pick(cfg, {"title": "Perception Engineer", "variant": "gone"}) == "perception"  # removed variant
    assert validate_choice(cfg, "auto") is None and validate_choice(cfg, "mle") == "mle"
    with pytest.raises(ValueError, match="did you mean 'mle'"):
        validate_choice(cfg, "mlee")
    with pytest.raises(ValueError, match="only one resume"):
        validate_choice(config_mod.parse({}), "mle")


def _add(conn, sid, title, desc):
    jid, _ = db.upsert_job(conn, JobPosting("linkedin", sid, title, "Acme", description=desc))
    return jid


def test_scoring_uses_the_variant_bank(vprofile):
    from jobapp.resume.matching import Matcher
    from jobapp.resume.rescore import rescore_all
    cfg = config_mod.load()
    conn = db.connect()
    desc = "Python, PyTorch, Kubernetes and C++ with ROS and OpenCV."
    a = _add(conn, "1", "Perception Engineer", desc)
    b = _add(conn, "2", "Machine Learning Engineer", desc)
    rescore_all(cfg, conn)
    ja, jb = db.get_job(conn, a), db.get_job(conn, b)
    assert set(ja["matched"]) == {"C++", "ROS", "OpenCV"} and "PyTorch" in ja["missing"]
    assert set(jb["matched"]) == {"Machine Learning", "Python", "PyTorch", "Kubernetes"} and "OpenCV" in jb["missing"]
    assert Matcher.from_config(cfg).score_job(ja).variant == "perception"


def test_cli_build_variant_override_list_show(vprofile, monkeypatch):
    from typer.testing import CliRunner
    from jobapp.cli import app
    from jobapp.resume import service
    cfg = config_mod.load()
    conn = db.connect()
    jid = _add(conn, "7", "Perception Engineer", "C++ and Python and PyTorch")
    used = {}

    def fake_build(cfg, **kw):
        used.update(kw)
        return service.BuildResult(paths.output_dir() / "x.pdf", [], [], [], [], 1, [], kw["variant"])
    monkeypatch.setattr(service, "build_pdf", fake_build)
    r = CliRunner().invoke(app, ["build", jid, "--variant", "mle"])
    assert r.exit_code == 0, r.output
    assert used["variant"] == "mle" and "resume: mle" in r.output
    j = db.get_job(conn, jid)
    assert j["variant"] == "mle" and "Python" in j["matched"]  # re-scored with the mle bank
    r = CliRunner().invoke(app, ["list", "--json"])
    assert json.loads(r.output)[0]["variant"] == "mle"
    r = CliRunner().invoke(app, ["show", jid])
    assert "resume: mle (your choice" in r.output
    r = CliRunner().invoke(app, ["build", jid, "--variant", "auto"])
    assert used["variant"] == "perception" and db.get_job(conn, jid)["variant"] is None
    r = CliRunner().invoke(app, ["build", jid, "--variant", "nope"])
    assert r.exit_code != 0 and "isn't one of your resumes" in (r.output + str(r.exception))
    r = CliRunner().invoke(app, ["list"], env={"COLUMNS": "250"})
    assert "perception*" in r.output and "picked automatically" in r.output


def test_real_build_with_each_variant(vprofile):
    from jobapp.resume import tex as texmod
    from jobapp.resume.service import build_pdf
    cfg = config_mod.load()
    (vprofile / "resume" / "mle.tex").write_text(
        (vprofile / "resume" / "mle.tex").read_text().replace("Alex Example", "Alex Example MLE"))
    for v in ("perception", "mle"):
        res = build_pdf(cfg, company="Acme", role="Engineer", description="Python, C++ and ROS", variant=v,
                        dry_run=texmod.detect() is None)
        assert res.variant == v
    res = build_pdf(cfg, company="Acme", role="Machine Learning Engineer", description="Python", dry_run=True)
    assert res.variant == "mle" and res.matched == ["Machine Learning", "Python"]


def test_single_tex_config_unchanged(profile):
    from jobapp.resume.service import build_pdf
    res = build_pdf(config_mod.load(), company="Acme", role="Analyst", description="Excel and SQL", dry_run=True)
    assert res.variant is None and "Excel" in res.matched


def test_web_variant_dropdown_api(vprofile):
    from fastapi.testclient import TestClient
    from jobapp.web.server import create_app
    conn = db.connect()
    jid = _add(conn, "9", "Machine Learning Engineer", "Python")
    c = TestClient(create_app())
    assert c.get("/api/variants").json() == {"variants": ["perception", "mle"], "default": "perception"}
    row = [j for j in c.get("/api/jobs").json() if j["id"] == jid][0]
    assert row["variant"] == "mle" and row["variant_chosen"] is False
    r = c.post(f"/api/jobs/{jid}/variant", json={"variant": "perception"}, headers={"X-JobApp": "1"})
    assert r.json()["ok"] and r.json()["variant"] == "perception" and r.json()["variant_chosen"]
    r = c.post(f"/api/jobs/{jid}/variant", json={"variant": "zzz"}, headers={"X-JobApp": "1"})
    assert r.status_code == 400
    r = c.post(f"/api/jobs/{jid}/variant", json={"variant": "auto"}, headers={"X-JobApp": "1"})
    assert r.json()["variant"] == "mle" and not r.json()["variant_chosen"]
    assert "setVariant" in c.get("/").text


def test_mcp_tools_show_variant(vprofile):
    from jobapp.agent import tools
    conn = db.connect()
    jid = _add(conn, "11", "Perception Engineer", "C++")
    out = tools.list_jobs()
    assert out["jobs"][0]["resume_variant"] == "perception (auto)"
    assert tools.job_details(jid)["job"]["variant"] == "perception"


def test_doctor_checks_every_variant(vprofile):
    from jobapp.doctor import OK, FAIL, check_resume
    cfg = config_mod.load()
    assert check_resume(cfg).status == OK and "2 variants" in check_resume(cfg).detail
    (vprofile / "resume" / "mle.tex").unlink()
    c = check_resume(cfg)
    assert c.status == FAIL and "mle" in c.name
