"""Release checks (phase 8): docs present, version consistent, packaging includes data, no personal data tracked."""
import re
import subprocess
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = pytest.importorskip("tomli")
from typer.testing import CliRunner

import jobapp
from jobapp.cli import app

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text())
VERSION = PYPROJECT["project"]["version"]


@pytest.mark.parametrize("rel", [
    "README.md", "CHANGELOG.md", "LICENSE", ".gitignore", "CLAUDE.md",
    "docs/ARCHITECTURE.md", "docs/ADDING_A_SOURCE.md", "scripts/privacy_scan.sh",
    ".claude/settings.json",
])
def test_release_file_present(rel):
    p = REPO / rel
    assert p.is_file() and p.read_text().strip(), rel


def test_license_is_mit():
    text = (REPO / "LICENSE").read_text()
    assert text.startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in text
    assert PYPROJECT["project"]["license"]["text"] == "MIT"


def test_version_consistent():
    assert jobapp.__version__ == VERSION
    r = CliRunner().invoke(app, ["version"])
    assert r.exit_code == 0 and VERSION in r.stdout
    assert re.search(rf"^## v{re.escape(VERSION)}\b", (REPO / "CHANGELOG.md").read_text(), re.M)


def test_readme_covers_novice_path():
    readme = (REPO / "README.md").read_text()
    for needle in ["Install with Claude", "Manual install", "/setup", "jobapp init", "jobapp doctor",
                   "mcp-config", "claude_desktop_config.json", "report-bug", "screenshot"]:
        assert needle.lower() in readme.lower(), needle


def test_readme_mentions_every_top_level_command():
    readme = (REPO / "README.md").read_text() + (REPO / "CLAUDE.md").read_text()
    names = [c.name or c.callback.__name__ for c in app.registered_commands]
    names += [g.name for g in app.registered_groups]
    hidden = {"mcp"}  # stdio server, launched by Claude Desktop via mcp-config
    missing = [n for n in names if n not in hidden and f"jobapp {n}" not in readme]
    assert not missing, missing


@pytest.mark.parametrize("doc", ["README.md", "CLAUDE.md", "docs/ARCHITECTURE.md", "docs/ADDING_A_SOURCE.md"])
def test_relative_links_resolve(doc):
    path = REPO / doc
    for target in re.findall(r"\]\(([^)#\s]+)", path.read_text()):
        if re.match(r"[a-z]+:", target):
            continue
        assert (path.parent / target).exists(), f"{doc}: broken link {target}"


def test_slash_commands_exist():
    cmds = {p.stem for p in (REPO / ".claude/commands").glob("*.md")}
    assert {"setup", "find-jobs", "tailor", "import-resume", "applied", "update", "report-bug"} <= cmds


def test_gitignore_keeps_personal_data_out():
    ignored = (REPO / ".gitignore").read_text().split()
    for pat in [".env", "*.db", "output/", "import/", "JobApplication-data/", ".claude/settings.local.json"]:
        assert pat in ignored, pat


def test_no_personal_or_generated_files_tracked():
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    bad = [f for f in files if re.search(r"(\.db$|\.env$|\.pdf$|\.docx$|(^|/)output/|__pycache__)", f)]
    assert not bad, bad


def test_wheel_includes_package_data():
    force = PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    for src in force:
        assert (REPO / src).exists(), src
    assert (REPO / "examples/profile/config.yaml").is_file()
    assert (REPO / "examples/profile/resume/resume.tex").is_file()
    assert any((REPO / "prompts").glob("*.md"))
    pkg = REPO / "src/jobapp"
    for rel in ["web/index.html", "web/job.html"]:
        assert (pkg / rel).is_file(), rel
    assert list((pkg / "db/migrations").glob("[0-9][0-9][0-9]_*.sql"))
