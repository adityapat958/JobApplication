import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def jobapp_home(tmp_path, monkeypatch):
    home = tmp_path / "data"
    monkeypatch.setenv("JOBAPP_HOME", str(home))
    return home


@pytest.fixture
def profile(jobapp_home):
    from jobapp import profile as p
    p.init()
    return jobapp_home


@pytest.fixture
def conn(tmp_path):
    from jobapp import db
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")
