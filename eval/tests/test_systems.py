import pytest

from cmeval.cli import main
from cmeval.systems import ADAPTERS, SystemSpec, SystemsError, load_systems, make_system, parse_systems


def test_parse_systems():
    specs = parse_systems({"system": [
        {"name": "fake-a", "adapter": "fake"},
        {"name": "fake-b", "adapter": "fake", "granularity": "file", "suffix": ".go"},
    ]})
    assert specs == [SystemSpec("fake-a", "fake", {}), SystemSpec("fake-b", "fake", {"granularity": "file", "suffix": ".go"})]


@pytest.mark.parametrize(
    "data, message",
    [
        ({}, "needs at least one"),
        ({"system": []}, "needs at least one"),
        ({"system": [{"name": "a", "adapter": "fake"}], "extra": 1}, "unknown top-level keys: extra"),
        ({"system": [{"adapter": "fake"}]}, "name None"),
        ({"system": [{"name": "has space", "adapter": "fake"}]}, "must use only"),
        ({"system": [{"name": "a", "adapter": "fake"}, {"name": "a", "adapter": "fake"}]}, "used twice"),
        ({"system": [{"name": "a", "adapter": "nope"}]}, "unknown adapter 'nope'"),
    ],
)
def test_parse_systems_rejects_bad_configs(data, message):
    with pytest.raises(SystemsError, match=message):
        parse_systems(data)


def test_make_system_passes_params_and_reports_bad_ones():
    system = make_system(SystemSpec("f", "fake", {"granularity": "file"}))
    assert system.name == "f" and system.granularity == "file"
    with pytest.raises(SystemsError, match="bad settings for adapter 'fake'"):
        make_system(SystemSpec("f", "fake", {"colour": "red"}))
    with pytest.raises(SystemsError, match="granularity 'chunk'"):
        make_system(SystemSpec("f", "fake", {"granularity": "chunk"}))


def test_make_system_reports_a_missing_package(monkeypatch):
    monkeypatch.setitem(ADAPTERS, "ghost", "cmeval_no_such_module:Thing")
    with pytest.raises(SystemsError, match="needs a package that is not installed"):
        make_system(SystemSpec("g", "ghost", {}))


def test_load_systems_and_cli(tmp_path, capsys):
    path = tmp_path / "x.toml"
    path.write_text('[[system]]\nname = "fake-line"\nadapter = "fake"\n')
    assert load_systems(path) == [SystemSpec("fake-line", "fake", {})]
    assert main(["systems", str(path)]) == 0
    assert "fake-line" in capsys.readouterr().out
    path.write_text("[[system]\n")
    assert main(["systems", str(path)]) == 1
    assert "not valid TOML" in capsys.readouterr().err


def test_shipped_smoke_config_loads():
    from pathlib import Path

    specs = load_systems(Path(__file__).parents[1] / "configs" / "smoke.toml")
    systems = [make_system(s) for s in specs]
    assert [s.granularity for s in systems] == ["line", "file"]
    assert systems[0].index_key() == systems[1].index_key()  # same index, different reporting
