"""Settings resolve env -> .env -> built-in default, and never explode."""

import pytest

from volley import config


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    for name in config.DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    return tmp_path


def test_ships_without_credentials():
    """Nothing secret is baked in; .env supplies it."""
    assert config.spreadsheet_id() == ""
    assert config.profixio()["league_id"] == ""
    assert config.profixio()["key"] == ""


def test_env_file_beats_the_default(isolated_env):
    (isolated_env / ".env").write_text("VOLLEY_SPREADSHEET_ID=from_file\n")
    assert config.spreadsheet_id() == "from_file"


def test_environment_beats_the_env_file(isolated_env, monkeypatch):
    (isolated_env / ".env").write_text("VOLLEY_SPREADSHEET_ID=from_file\n")
    monkeypatch.setenv("VOLLEY_SPREADSHEET_ID", "from_env")
    assert config.spreadsheet_id() == "from_env"


def test_a_missing_env_file_is_not_an_error(isolated_env):
    assert not (isolated_env / ".env").exists()
    assert config.read_env_file() == {}
    assert config.spreadsheet_id() == ""      # empty, not an exception


def test_env_file_parsing(isolated_env):
    (isolated_env / ".env").write_text(
        "# a comment\n"
        "\n"
        'QUOTED="double"\n'
        "SINGLE='single'\n"
        "SPACED =  padded  \n"
        "no_equals_sign\n"
        "EMPTY=\n"
    )
    values = config.read_env_file()
    assert values["QUOTED"] == "double"
    assert values["SINGLE"] == "single"
    assert values["SPACED"] == "padded"
    assert values["EMPTY"] == ""
    assert "no_equals_sign" not in values


def test_an_empty_env_value_falls_through_to_the_default(isolated_env):
    (isolated_env / ".env").write_text("VOLLEY_SPREADSHEET_ID=\n")
    assert config.spreadsheet_id() == config.DEFAULTS["VOLLEY_SPREADSHEET_ID"]


def test_profixio_settings_travel_together():
    settings = config.profixio()
    assert set(settings) == {"league_id", "team_id", "key", "team_name"}


def test_env_supplies_the_profixio_credentials(isolated_env):
    (isolated_env / ".env").write_text(
        "VOLLEY_PROFIXIO_LEAGUE_ID=111\n"
        "VOLLEY_PROFIXIO_TEAM_ID=222\n"
        "VOLLEY_PROFIXIO_KEY=333\n"
    )
    settings = config.profixio()
    assert (settings["league_id"], settings["team_id"], settings["key"]) == ("111", "222", "333")
