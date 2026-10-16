import pytest
import yaml

from jobapp import config, paths


def test_example_config_valid():
    cfg = config.load(paths.examples_profile() / "config.yaml")
    assert cfg.profile.name == "Alex Example"
    assert cfg.sources.linkedin.enabled
    assert cfg.filters.title_include == ["analyst", "consultant"]


def test_defaults_from_empty():
    cfg = config.parse({})
    assert cfg.filters.title_include == []
    assert cfg.schedule.times == ["09:00", "18:00"]


@pytest.mark.parametrize("data,needle", [
    ({"sources": {"linkedn": {}}}, "did you mean 'linkedin'"),
    ({"filtres": {}}, "did you mean 'filters'"),
    ({"filters": {"title_inclde": []}}, "did you mean 'title_include'"),
    ({"filters": {"job_types": ["fultime"]}}, "did you mean 'fulltime'"),
    ({"profile": {"locale": "nb"}}, "is not allowed"),
    ({"schedule": {"times": ["9am"]}}, "not a time like 09:00"),
    ({"resume": {"output_name": "{first}_{bogus}"}}, "unknown placeholder"),
    ({"sources": {"linkedin": {"searches": [{"keyword": "x"}]}}}, "did you mean 'keywords'"),
])
def test_friendly_errors(data, needle):
    with pytest.raises(config.ConfigError) as e:
        config.parse(data)
    assert any(needle in p for p in e.value.problems), e.value.problems


def test_bad_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("profile:\n\tname: x\n")
    with pytest.raises(config.ConfigError) as e:
        config.load(p)
    assert "tabs" in e.value.problems[0]


def test_missing_file(tmp_path):
    with pytest.raises(config.ConfigError) as e:
        config.load(tmp_path / "nope.yaml")
    assert "jobapp init" in e.value.problems[0]


def test_roundtrip(tmp_path):
    cfg = config.load(paths.examples_profile() / "config.yaml")
    p = tmp_path / "out.yaml"
    config.save(cfg, p)
    assert config.load(p) == cfg
    assert yaml.safe_load(p.read_text())["profile"]["name"] == "Alex Example"
