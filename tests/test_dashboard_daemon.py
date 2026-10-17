import json, socket, time, urllib.request
import pytest
from jobapp.web import daemon


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBAPP_HOME", str(tmp_path / "home"))
    from jobapp.profile import init
    init()
    monkeypatch.setattr(daemon.webbrowser, "open", lambda url: None)
    yield tmp_path


def _busy_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    return s, s.getsockname()[1]


def test_free_port_skips_busy():
    s, p = _busy_port()
    try:
        assert daemon.free_port(p) != p
    finally:
        s.close()


def test_background_start_survives_and_stops(profile):
    s, busy = _busy_port()       # something else already on the preferred port
    try:
        msg = daemon.start(port=busy, open_browser=False)
    finally:
        s.close()
    assert "running at" in msg, msg
    st = json.loads(daemon._state_file().read_text())
    assert st["port"] != busy
    with urllib.request.urlopen(f"http://127.0.0.1:{st['port']}/api/jobs", timeout=5) as r:
        assert r.status == 200
    assert "already running" in daemon.start(open_browser=False)
    assert "running at" in daemon.status()
    assert daemon.stop() == "Dashboard stopped."
    time.sleep(0.5)
    assert "not running" in daemon.status()


def test_setup_does_not_ask_obsidian():
    from pathlib import Path
    txt = (Path(__file__).parents[1] / ".claude/commands/setup.md").read_text()
    assert "Do you use Obsidian" not in txt
    assert "serve --background" in txt
