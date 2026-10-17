import json

from typer.testing import CliRunner

from jobapp import paths
from jobapp.cli import app

runner = CliRunner()


def test_init_validate_doctor(jobapp_home):
    r = runner.invoke(app, ["init"])
    assert r.exit_code == 0, r.output
    assert (jobapp_home / "config.yaml").exists()
    assert (jobapp_home / "resume" / "resume.tex").exists()
    assert (jobapp_home / "jobs.db").exists()
    r = runner.invoke(app, ["config", "validate"])
    assert r.exit_code == 0 and "look good" in r.output
    r = runner.invoke(app, ["doctor", "--offline", "--json"])
    checks = json.loads(r.output)
    names = {c["name"]: c["status"] for c in checks}
    assert names["Settings (config.yaml)"] == "ok"
    assert names["Database"] == "ok"
    # second init doesn't clobber edits
    (jobapp_home / "config.yaml").write_text("profile: {name: Edited Person}\n")
    runner.invoke(app, ["init"])
    assert "Edited" in (jobapp_home / "config.yaml").read_text()


def test_validate_reports_problem(jobapp_home):
    runner.invoke(app, ["init"])
    (jobapp_home / "config.yaml").write_text("sources: {linkedn: {}}\n")
    r = runner.invoke(app, ["config", "validate"])
    assert r.exit_code == 1
    assert "did you mean 'linkedin'" in r.output


def test_version():
    r = runner.invoke(app, ["version"])
    assert "0.1.3" in r.output


def test_home_env(jobapp_home):
    assert paths.home() == jobapp_home
