import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "privacy_scan.sh"


def test_repo_is_clean():
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _scan_tmp(tmp_path, content):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "privacy_scan.sh")
    (tmp_path / "f.txt").write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return subprocess.run(["bash", "scripts/privacy_scan.sh"], cwd=tmp_path, capture_output=True, text=True)


def test_detects_home_path(tmp_path):
    assert _scan_tmp(tmp_path, "path " + "/ho" + "me/someone/x").returncode == 1


def test_detects_phone(tmp_path):
    assert _scan_tmp(tmp_path, "call +1 (55" + "5) 123-" + "4567 now").returncode == 1


def test_detects_token(tmp_path):
    assert _scan_tmp(tmp_path, "token gh" + "p_abcdef").returncode == 1


def test_ok_plain(tmp_path):
    assert _scan_tmp(tmp_path, "nothing personal, job id 4012345678").returncode == 0


def test_detects_test_user_names(tmp_path):
    for word in ("Kshi" "tij", "hase" "eb", "ADI" "TYA", "Chaud" "hary", "Kha" "lid", "Patward" "han",
                 "kshi" "tijc", "hase" "ebkh" "alid"):
        d = tmp_path / word
        d.mkdir()
        assert _scan_tmp(d, f"profile of {word} here").returncode == 1, word
