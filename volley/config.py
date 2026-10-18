"""Settings, resolved from the environment, then `.env`, then a built-in default.

Everything here has a working default for this club, so the app starts usable
with nothing configured. Only the defaults are club-specific; the behaviour is
not - point the env vars elsewhere and it follows.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

# No credentials here. The spreadsheet id and the Profixio key belong in .env,
# which is git-ignored - see .env.example.
DEFAULTS = {
    "VOLLEY_SPREADSHEET_ID": "",
    "VOLLEY_PROFIXIO_LEAGUE_ID": "",
    "VOLLEY_PROFIXIO_TEAM_ID": "",
    "VOLLEY_PROFIXIO_KEY": "",
    "VOLLEY_TEAM_NAME": "Elden VBK",
    "VOLLEY_CLUB_NAME": "Elden VBK",
    "VOLLEY_LOGO": str(ROOT / "assets" / "elden-vbk.png"),
    # Which tabs a push writes. PlayerSetStats drives the dashboard; Events is
    # the append-only archive of the raw rows, and the only thing that makes a
    # lost local buffer recoverable - an aggregate cannot be taken apart again.
    "VOLLEY_PUSH_TABS": "PlayerSetStats,Events,Matches",
    # A service-account key, if you have one. Share the spreadsheet with the
    # account's email and it works like any other collaborator.
    "VOLLEY_SERVICE_ACCOUNT": str(ROOT / "service_account.json"),
}


def read_env_file(path: Path | None = None) -> dict:
    """Parse a KEY=value file. Missing file is not an error."""
    path = Path(path) if path is not None else ENV_FILE
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def get(name: str, default: str | None = None) -> str:
    """Environment wins, then `.env`, then the built-in default."""
    if os.environ.get(name):
        return os.environ[name]
    from_file = read_env_file().get(name)
    if from_file:
        return from_file
    if default is not None:
        return default
    return DEFAULTS.get(name, "")


def spreadsheet_id() -> str:
    return get("VOLLEY_SPREADSHEET_ID")


def team_name() -> str:
    return get("VOLLEY_TEAM_NAME")


def club_name() -> str:
    return get("VOLLEY_CLUB_NAME")


def logo_path() -> Path:
    return Path(get("VOLLEY_LOGO"))


def service_account_path() -> Path:
    return Path(get("VOLLEY_SERVICE_ACCOUNT"))


def push_tabs() -> list:
    """Tab names a push writes, in order."""
    return [part.strip() for part in get("VOLLEY_PUSH_TABS").split(",") if part.strip()]


def profixio() -> dict:
    return {
        "league_id": get("VOLLEY_PROFIXIO_LEAGUE_ID"),
        "team_id": get("VOLLEY_PROFIXIO_TEAM_ID"),
        "key": get("VOLLEY_PROFIXIO_KEY"),
        "team_name": team_name(),
    }
