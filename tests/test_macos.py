import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from jobapp import config, platform as plat, schedule, secrets


@pytest.fixture
def cfg(profile):
    return config.parse({"schedule": {"times": ["18:30", "09:00", "09:00"]}})


def test_plist_generation(cfg, profile):
    d = plistlib.loads(schedule.plist_bytes(cfg))
    assert d["Label"] == "com.jobapplication.poll"
    assert d["StartCalendarInterval"] == [{"Hour": 9, "Minute": 0}, {"Hour": 18, "Minute": 30}]
    assert d["ProgramArguments"] == [sys.executable, "-m", "jobapp.cli_entry", "poll"]
    assert d["EnvironmentVariables"]["JOBAPP_HOME"] == str(profile)
    assert "/opt/homebrew/bin" in d["EnvironmentVariables"]["PATH"]
    assert "/Library/TeX/texbin" in d["EnvironmentVariables"]["PATH"]
    assert d["StandardOutPath"].endswith("logs/schedule.log")
    assert d["RunAtLoad"] is False
    assert schedule.plist_bytes(cfg).startswith(b"<?xml")


def test_crontab_lines(cfg, profile):
    lines = schedule.crontab_lines(cfg)
    assert len(lines) == 2
    assert lines[0].startswith("0 9 * * * JOBAPP_HOME=")
    assert lines[1].startswith("30 18 * * * ")
    assert all(l.endswith(schedule.CRON_TAG) and "-m jobapp.cli_entry poll" in l for l in lines)


def test_quote():
    assert schedule._q("/a b/c") == "'/a b/c'"
    assert schedule._q("/plain/path") == "/plain/path"


def test_install_linux_prints_and_does_not_touch_crontab(cfg, monkeypatch):
    monkeypatch.setattr(schedule, "is_mac", lambda: False)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    msg = schedule.install(cfg)
    assert "crontab -e" in msg and "30 18 * * *" in msg
    assert calls == []
    assert "crontab -e" in schedule.remove()


def test_install_mac_writes_plist_and_loads(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(schedule, "is_mac", lambda: True)
    monkeypatch.setattr(schedule, "plist_path", lambda: tmp_path / "LaunchAgents" / "com.jobapplication.poll.plist")
    calls = []

    def fake(*args):
        calls.append(args)
        out = "123\t0\tcom.jobapplication.poll\n" if args[0] == "list" else ""
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(schedule, "_launchctl", fake)
    msg = schedule.install(cfg)
    p = schedule.plist_path()
    assert p.exists() and "every day at 09:00, 18:30" in msg
    assert calls == [("load", "-w", str(p))]
    schedule.install(cfg)  # reinstall unloads first
    assert calls[1] == ("unload", str(p))
    assert "on: every day at 09:00, 18:30" in schedule.status(cfg)
    assert schedule.remove() == "Automatic searches are off." and not p.exists()
    assert "off" in schedule.status(cfg)


def test_reveal_commands(monkeypatch, tmp_path):
    f = tmp_path / "a.pdf"
    f.write_text("x")
    monkeypatch.setattr(plat, "is_mac", lambda: True)
    assert plat.reveal_command(f) == ["open", "-R", str(f)]
    assert plat.folder_label() == "Show in Finder"
    monkeypatch.setattr(plat, "is_mac", lambda: False)
    monkeypatch.setattr(plat.sys, "platform", "linux")
    assert plat.reveal_command(f) == ["xdg-open", str(tmp_path)]
    assert plat.folder_label() == "Show in folder"


def test_reveal_handles_missing_opener(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("no opener")
    monkeypatch.setattr(plat.subprocess, "Popen", boom)
    assert plat.reveal(tmp_path / "a.pdf") is False


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, svc, name):
        return self.store.get((svc, name))

    def set_password(self, svc, name, value):
        self.store[(svc, name)] = value


def test_secrets_env_keyring_dotenv(profile, monkeypatch):
    import keyring as real
    fake = FakeKeyring()
    monkeypatch.setattr(real, "get_password", fake.get_password)
    monkeypatch.setattr(real, "set_password", fake.set_password)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert secrets.get("ANTHROPIC_API_KEY") is None
    assert secrets.set("ANTHROPIC_API_KEY", "k1") == "keychain"
    assert secrets.get("ANTHROPIC_API_KEY") == "k1"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert secrets.get("ANTHROPIC_API_KEY") == "from-env"


def test_secrets_fallback_to_dotenv(profile, monkeypatch):
    import keyring as real

    def broken(*a, **k):
        raise RuntimeError("no backend")
    monkeypatch.setattr(real, "get_password", broken)
    monkeypatch.setattr(real, "set_password", broken)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    where = secrets.set("GEMINI_API_KEY", "g1")
    env = Path(where)
    assert env.name == ".env" and (env.stat().st_mode & 0o777) == 0o600
    assert secrets.get("GEMINI_API_KEY") == "g1"
    env.write_text('# comment\nexport GEMINI_API_KEY="g2"\n')
    assert secrets.get("GEMINI_API_KEY") == "g2"


def test_cli_schedule_and_key_status(profile, monkeypatch):
    from typer.testing import CliRunner
    from jobapp.cli import app
    monkeypatch.setattr(schedule, "is_mac", lambda: False)
    r = CliRunner().invoke(app, ["schedule", "install"])
    assert r.exit_code == 0 and "crontab" in r.output
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    r = CliRunner().invoke(app, ["key", "status"])
    assert "ANTHROPIC_API_KEY: set" in r.output and "x\n" not in r.output
