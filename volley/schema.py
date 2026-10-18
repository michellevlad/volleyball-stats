"""The vocabulary every other module agrees on: actions, results, columns, tabs.

Keeping this in one place means the entry UI, the pandas aggregations and the
Google Sheets layout can never drift apart.
"""

from __future__ import annotations

# --- tabs in the spreadsheet ------------------------------------------------

TAB_ROSTER = "Roster"
TAB_MATCHES = "Matches"
TAB_EVENTS = "Events"
TAB_LINEUP = "Lineup"
TAB_SET_STATS = "PlayerSetStats"
TAB_PLAYER_STATS = "PlayerMatchStats"
TAB_TEAM_STATS = "TeamMatchStats"
TAB_ROLE_STATS = "PlayerRoleStats"

# --- action taxonomy --------------------------------------------------------

SERVE = "SERVE"
ATTACK = "ATTACK"
BLOCK = "BLOCK"
DIG = "DIG"
RECEPTION = "RECEPTION"
SET = "SET"

# action -> valid results, in the order they should appear as buttons
ACTIONS = {
    SERVE: ["ace", "in", "error"],
    ATTACK: ["kill", "attempt", "error"],
    BLOCK: ["kill", "attempt", "error"],
    DIG: ["dig", "error"],
    RECEPTION: ["perfect", "playable", "error"],
    SET: ["assist", "attempt", "error"],
}

# Reception on the familiar 0-3 passing scale, but with only the three calls a
# human can actually make at video speed. The 1 tier is deliberately unused:
# "playable" is a 2, and the jump straight to 0 reflects that a poor-but-
# playable ball is still far better than a shank.
RECEPTION_VALUES = {"perfect": 3, "playable": 2, "error": 0}

ACTION_ORDER = [SERVE, ATTACK, RECEPTION, DIG, BLOCK, SET]

# Short labels for the result buttons, so the grid stays readable.
# Plain words only. A parenthetical number would suggest a single scale, and a
# "0" means something different for an attack than for a reception.
RESULT_LABELS = {
    (BLOCK, "kill"): "block point",
    (BLOCK, "attempt"): "touch",
    (SET, "attempt"): "set",
}

# Results that end the rally in our favour and so bump our score by one.
POINT_RESULTS = {
    (SERVE, "ace"),
    (ATTACK, "kill"),
    (BLOCK, "kill"),
}


# --- roles ------------------------------------------------------------------
# A role belongs to (player, match, set), not to the player: someone can set in
# one set and play opposite in the next, and the whole point is being able to
# compare a player's numbers across the roles they actually played.
ROLES = ["OH", "MB", "S", "OP", "L", "DS"]

ROLE_NAMES = {
    "OH": "Outside hitter",
    "MB": "Middle blocker",
    "S": "Setter",
    "OP": "Opposite",
    "L": "Libero",
    "DS": "Defensive specialist",
}


# People write the same role several ways; accept them all and store one.
ROLE_ALIASES = {
    "OH": "OH", "OUTSIDE": "OH", "WS": "OH", "OUTSIDE HITTER": "OH",
    "MB": "MB", "M": "MB", "MID": "MB", "MIDDLE": "MB", "MIDDLE BLOCKER": "MB",
    "S": "S", "SET": "S", "SETTER": "S",
    "OP": "OP", "OPP": "OP", "OPPO": "OP", "OPPOSITE": "OP",
    "L": "L", "LIB": "L", "LIBERO": "L",
    "DS": "DS", "DEFENSIVE SPECIALIST": "DS",
}


def normalise_role(value) -> str:
    """'OPP' -> 'OP'. Unknown values are kept as typed rather than discarded."""
    text = str(value or "").strip()
    return ROLE_ALIASES.get(text.upper(), text)


class InvalidEvent(ValueError):
    """Raised when an (action, result) pair is not part of the taxonomy."""


def validate(action: str, result: str) -> tuple[str, str]:
    """Normalise and check an (action, result) pair, or raise InvalidEvent."""
    action = str(action).strip().upper()
    result = str(result).strip().lower()
    if action not in ACTIONS:
        raise InvalidEvent(f"unknown action {action!r}")
    if result not in ACTIONS[action]:
        valid = ", ".join(ACTIONS[action])
        raise InvalidEvent(f"{result!r} is not a valid {action} result (expected: {valid})")
    return action, result


def is_point(action: str, result: str) -> bool:
    return (action, result) in POINT_RESULTS


def result_label(action: str, result: str) -> str:
    return RESULT_LABELS.get((action, result), result)


# --- column layouts ---------------------------------------------------------

ROSTER_COLUMNS = ["player_id", "number", "name", "position", "active"]

MATCH_COLUMNS = [
    "match_id",
    "date",
    "time",
    "opponent",
    # Both sides by name, and the score the way the league prints it: home
    # first. `official_result`/`official_sets` stay from our point of view.
    "home_team",
    "away_team",
    "result_home",
    "sets_home",
    "home_away",
    "competition",
    "sets_won",
    "sets_lost",
    "video_url",
    "profixio_match_id",
    "squad",
    "official_result",
    "official_sets",
    "notes",
]

# The fields you actually look at come first; the four after them are
# machinery. `event_id` is what makes pushing twice add nothing and
# re-importing a protocol safe, and `score_us`/`score_them` are what the
# set-by-set check against Profixio compares - neither is decoration.
EVENT_COLUMNS = [
    "match_id",
    "match_date",
    "match_name",
    "set_no",
    "player_num",
    "player_name",
    "player_role",
    "action",
    "action_result",
    "is_point",
    # Who an assist was set to. Blank on everything else.
    "target_num",
    "source",
    "event_id",
    "seq",
    "score_us",
    "score_them",
]

# Where a row came from: "manual" (entered here) or "profixio" (imported from
# the official protocol). Re-importing only ever replaces "profixio" rows.
SOURCE_MANUAL = "manual"
SOURCE_PROFIXIO = "profixio"

# Local-only bookkeeping column, never written to the spreadsheet.
LOCAL_ONLY_COLUMNS = ["synced"]

# Keyed by shirt number: it is unique within a match, and it is what you see
# on the court.
LINEUP_COLUMNS = ["match_id", "set_no", "player_num", "player_name", "player_role"]

PLAYER_STATS_COLUMNS = [
    "match_id",
    "match_date",
    "match_name",
    "player_num",
    "player_name",
    "player_role",
    "sets_played",
    # Counts only. Every rate - kill %, hitting efficiency, pass rating,
    # points - is a calculated field in Looker, because a stored rate cannot be
    # re-aggregated: averaging per-set hitting efficiencies into a season
    # figure gives the wrong number, while SUM(kills)/SUM(attempts) is always
    # right at whatever grain the chart is on.
    "kills",
    "attack_errors",
    "attempts",
    "aces",
    "serve_errors",
    "serves",
    "receptions_perfect",
    "receptions_playable",
    "reception_errors",
    "reception_count",
    "blocks",
    "block_errors",
    "block_attempts",
    "digs",
    "dig_errors",
    "assists",
    "set_errors",
    "set_attempts",
]

TEAM_STATS_COLUMNS = [
    "match_id",
    "match_date",
    "match_name",
    "sets_played",
    "set_scores",
    "sets_won",
    "sets_lost",
] + [c for c in PLAYER_STATS_COLUMNS if c not in {
    "match_id", "match_date", "match_name", "player_num",
    "player_name", "player_role", "sets_played",
}]

# The finest grain there is: one row per player per set. Everything else can be
# summed out of it, and it is the shape a per-set spreadsheet already has.
SET_STATS_COLUMNS = [
    "match_id",
    "match_date",
    "match_name",
    "set_no",
    "player_num",
    "player_name",
    "player_role",
] + [c for c in PLAYER_STATS_COLUMNS if c not in {
    "match_id", "match_date", "match_name", "player_num",
    "player_name", "player_role", "sets_played",
}]

ROLE_STATS_COLUMNS = [
    "player_num",
    "player_name",
    "player_role",
    "matches",
    "sets_played",
] + [c for c in PLAYER_STATS_COLUMNS if c not in {
    "match_id", "match_date", "match_name", "player_num",
    "player_name", "player_role", "sets_played",
}]

TAB_HEADERS = {
    TAB_ROSTER: ROSTER_COLUMNS,
    TAB_MATCHES: MATCH_COLUMNS,
    TAB_EVENTS: EVENT_COLUMNS,
    TAB_LINEUP: LINEUP_COLUMNS,
    TAB_SET_STATS: SET_STATS_COLUMNS,
    TAB_PLAYER_STATS: PLAYER_STATS_COLUMNS,
    TAB_TEAM_STATS: TEAM_STATS_COLUMNS,
    TAB_ROLE_STATS: ROLE_STATS_COLUMNS,
}


# --- tab roles --------------------------------------------------------------
# Only these three can be mapped onto a tab that already exists in the user's
# spreadsheet. The aggregate tabs are rebuilt from scratch on every push, so
# pointing them at a hand-maintained tab would destroy it.
MAPPABLE_ROLES = {
    "roster": TAB_ROSTER,
    "matches": TAB_MATCHES,
    "events": TAB_EVENTS,
}

ROLE_COLUMNS = {
    "roster": ROSTER_COLUMNS,
    "matches": MATCH_COLUMNS,
    "events": EVENT_COLUMNS,
}
