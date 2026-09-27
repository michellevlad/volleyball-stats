"""Present so pytest puts the project root on sys.path and `volley` imports."""

import pytest


@pytest.fixture
def temp_store(tmp_path, monkeypatch):
    """Point every store file at a temp directory.

    One place, because patching them individually meant a newly added file
    (the lineup) silently kept writing to the real data/ and leaking between
    tests.
    """
    from volley import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    for attribute, filename in [
        ("EVENTS_FILE", "events.csv"),
        ("ROSTER_FILE", "roster.csv"),
        ("MATCHES_FILE", "matches.csv"),
        ("LINEUP_FILE", "lineup.csv"),
        ("SHEET_CONFIG_FILE", "sheet_config.json"),
    ]:
        monkeypatch.setattr(store, attribute, tmp_path / filename)
    return tmp_path


@pytest.fixture(autouse=True)
def never_touch_real_data(request, monkeypatch, tmp_path):
    """Backstop: a test that forgets to isolate must not write to data/.

    Tests that ask for `temp_store` manage their own paths; everything else
    gets a throwaway directory whether it asked for one or not.
    """
    if "temp_store" in request.fixturenames:
        return
    from volley import store

    guard = tmp_path / "guard"
    guard.mkdir(exist_ok=True)
    monkeypatch.setattr(store, "DATA_DIR", guard)
    for attribute, filename in [
        ("EVENTS_FILE", "events.csv"),
        ("ROSTER_FILE", "roster.csv"),
        ("MATCHES_FILE", "matches.csv"),
        ("LINEUP_FILE", "lineup.csv"),
        ("SHEET_CONFIG_FILE", "sheet_config.json"),
    ]:
        monkeypatch.setattr(store, attribute, guard / filename)
