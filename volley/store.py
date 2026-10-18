"""Local CSV buffer.

Every event is written to disk the moment it is entered. Streamlit reruns the
whole script on each click and a long video session is easy to interrupt, so
the local files - not session state - are the source of truth. The spreadsheet
is synced from here in batches.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config, schema

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EVENTS_FILE = DATA_DIR / "events.csv"
ROSTER_FILE = DATA_DIR / "roster.csv"
MATCHES_FILE = DATA_DIR / "matches.csv"
LINEUP_FILE = DATA_DIR / "lineup.csv"
SHEET_CONFIG_FILE = DATA_DIR / "sheet_config.json"

EVENT_BUFFER_COLUMNS = schema.EVENT_COLUMNS + schema.LOCAL_ONLY_COLUMNS

INT_COLUMNS = {
    "set_no", "seq", "number", "player_num", "score_us", "score_them",
    "sets_won", "sets_lost",
}
BOOL_COLUMNS = {"is_point", "synced", "active"}

_TRUE = {"true", "1", "yes", "y", "t"}


# --- helpers ----------------------------------------------------------------

def _coerce(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Force a frame to exactly `columns`, with sane dtypes for the known ones."""
    for column in columns:
        if column not in df.columns:
            df[column] = "" if column not in BOOL_COLUMNS else False
    df = df[columns].copy()
    for column in columns:
        if column in INT_COLUMNS:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
        elif column in BOOL_COLUMNS:
            df[column] = df[column].map(
                lambda value: str(value).strip().lower() in _TRUE
                if not isinstance(value, bool)
                else value
            )
        else:
            df[column] = df[column].fillna("").astype(str)
    return df


def concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate, dropping empties first.

    pandas deprecates inferring dtypes across empty/all-NA frames, and this
    runs on every single recorded event.
    """
    kept = [frame for frame in frames if len(frame)]
    if not kept:
        return frames[0] if frames else pd.DataFrame()
    if len(kept) == 1:
        return kept[0].copy()
    return pd.concat(kept, ignore_index=True)


def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return _coerce(pd.DataFrame(columns=columns), columns)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return _coerce(df, columns)


def _write(df: pd.DataFrame, path: Path, columns: list[str]) -> None:
    """Write via a temp file + rename so an interrupted save can't truncate data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    _coerce(df.copy(), columns).to_csv(tmp, index=False)
    os.replace(tmp, path)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "match"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def new_match_id(date: str, opponent: str) -> str:
    return f"{date}-{slugify(opponent)}"


# --- events -----------------------------------------------------------------

def load_events() -> pd.DataFrame:
    return _read(EVENTS_FILE, EVENT_BUFFER_COLUMNS)


def save_events(df: pd.DataFrame) -> None:
    _write(df, EVENTS_FILE, EVENT_BUFFER_COLUMNS)


def next_seq(events: pd.DataFrame, match_id: str, set_no: int) -> int:
    rows = events[(events["match_id"] == match_id) & (events["set_no"] == int(set_no))]
    return int(rows["seq"].max()) + 1 if len(rows) else 1


def build_event(
    match: dict,
    set_no: int,
    seq: int,
    player: dict,
    action: str,
    result: str,
    score_us: int = 0,
    score_them: int = 0,
    role: str = "",
    target_num=None,
    source: str = schema.SOURCE_MANUAL,
    event_id: str = "",
) -> dict:
    """Assemble one validated event row. Raises schema.InvalidEvent on bad input.

    The match is passed whole rather than by id because every row carries the
    date and a readable name - the Events tab has to be legible on its own,
    without joining back to Matches.
    """
    action, result = schema.validate(action, result)
    return {
        "match_id": match.get("match_id", ""),
        "match_date": match.get("date", ""),
        "match_name": match_name(match),
        "set_no": int(set_no),
        "player_num": int(player.get("number", player.get("player_num", 0)) or 0),
        "player_name": player.get("name", player.get("player_name", "")),
        "player_role": schema.normalise_role(role),
        "action": action,
        "action_result": result,
        "is_point": schema.is_point(action, result),
        "target_num": "" if target_num in (None, "") else int(target_num),
        "source": source,
        "event_id": event_id or new_id(),
        "seq": int(seq),
        "score_us": int(score_us),
        "score_them": int(score_them),
        "synced": False,
    }


def match_name(match: dict) -> str:
    """`Jomala IK C vs Elden VBK` - home side first, as the league prints it."""
    opponent = str(match.get("opponent", "") or "")
    us = config.team_name()
    if not opponent:
        return us
    if str(match.get("home_away", "")).strip().lower() == "home":
        return f"{us} vs {opponent}"
    return f"{opponent} vs {us}"


def append_event(event: dict) -> pd.DataFrame:
    events = concat_frames([load_events(), pd.DataFrame([event])])
    save_events(events)
    return events


def delete_event(event_id: str) -> pd.DataFrame:
    events = load_events()
    events = events[events["event_id"] != event_id]
    save_events(events)
    return events


def mark_synced(event_ids) -> pd.DataFrame:
    events = load_events()
    events.loc[events["event_id"].isin(list(event_ids)), "synced"] = True
    save_events(events)
    return events


def unsynced(events: pd.DataFrame) -> pd.DataFrame:
    return events[~events["synced"].astype(bool)]


def match_events(events: pd.DataFrame, match_id: str) -> pd.DataFrame:
    return events[events["match_id"] == match_id].sort_values(["set_no", "seq"])


def newest_first(events: pd.DataFrame, match_id: str, limit: int = None) -> pd.DataFrame:
    """Most recently registered first.

    The buffer is append-only, so row order *is* the order things were entered -
    which is not the same as set and sequence order once you move between sets.
    What you just did should be the first thing you see.
    """
    rows = events[events["match_id"] == match_id].iloc[::-1]
    return rows.head(limit) if limit else rows


def current_score(events: pd.DataFrame, match_id: str, set_no: int) -> tuple[int, int]:
    """Score after the last event of a set, used to restore state on reload."""
    rows = events[(events["match_id"] == match_id) & (events["set_no"] == int(set_no))]
    if not len(rows):
        return 0, 0
    last = rows.sort_values("seq").iloc[-1]
    return int(last["score_us"]), int(last["score_them"])


# --- roster -----------------------------------------------------------------

def load_roster() -> pd.DataFrame:
    return _read(ROSTER_FILE, schema.ROSTER_COLUMNS)


def save_roster(df: pd.DataFrame) -> None:
    df = df.copy()
    # Fill in player_ids for rows typed straight into the editor.
    missing = df["player_id"].astype(str).str.strip() == ""
    df.loc[missing, "player_id"] = "p" + df.loc[missing, "number"].astype(str)
    _write(df, ROSTER_FILE, schema.ROSTER_COLUMNS)


def active_players(roster: pd.DataFrame) -> pd.DataFrame:
    if not len(roster):
        return roster
    return roster[roster["active"].astype(bool)].sort_values("number")


def find_by_number(roster: pd.DataFrame, number: int) -> dict | None:
    rows = roster[roster["number"] == int(number)]
    return rows.iloc[0].to_dict() if len(rows) else None


# --- matches ----------------------------------------------------------------

def load_matches() -> pd.DataFrame:
    return _read(MATCHES_FILE, schema.MATCH_COLUMNS)


def save_matches(df: pd.DataFrame) -> None:
    _write(df, MATCHES_FILE, schema.MATCH_COLUMNS)


def upsert_match(match: dict) -> pd.DataFrame:
    matches = load_matches()
    matches = matches[matches["match_id"] != match["match_id"]]
    matches = concat_frames([matches, pd.DataFrame([match])])
    matches = matches.sort_values("date", ascending=False)
    save_matches(matches)
    return matches


# --- spreadsheet tab mapping ------------------------------------------------
# Which tab in the user's spreadsheet plays each role. Stored rather than
# assumed, because an existing spreadsheet names its tabs however it likes.

def load_sheet_config() -> dict:
    if not SHEET_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(SHEET_CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_sheet_config(config: dict) -> None:
    SHEET_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHEET_CONFIG_FILE.write_text(json.dumps(config, indent=2))


# --- squad call-up ----------------------------------------------------------

def squad_numbers(match: dict) -> list[int]:
    """Shirt numbers called up for a match. Empty means 'everyone active'."""
    raw = str(match.get("squad", "") or "")
    return [int(part) for part in re.findall(r"\d+", raw)]


def squad_players(roster: pd.DataFrame, match: dict, set_no: int = 1) -> pd.DataFrame:
    """Who is on court, wearing the number they wear *in this match*.

    The line-up wins when there is one, because a shirt number belongs to a
    match rather than to a season - Profixio reassigns them, and a player can
    borrow a shirt for one game. The roster is only the fallback.
    """
    lineup = match_lineup(match.get("match_id", ""), set_no)
    if len(lineup):
        # One shirt, one player - a duplicate number would collide in the UI.
        lineup = lineup.drop_duplicates("player_num", keep="first")
        return pd.DataFrame(
            [
                {
                    "player_id": f"p{int(row['player_num'])}",
                    "number": int(row["player_num"]),
                    "name": row["player_name"],
                    "position": row["player_role"],
                    "active": True,
                }
                for row in lineup.sort_values("player_num").to_dict("records")
            ],
            columns=schema.ROSTER_COLUMNS,
        )
    called = squad_numbers(match)
    if not called:
        return active_players(roster)
    return roster[roster["number"].isin(called)].sort_values("number")


def set_squad(match_id: str, numbers) -> pd.DataFrame:
    matches = load_matches()
    row = matches["match_id"] == match_id
    matches.loc[row, "squad"] = ",".join(str(int(n)) for n in sorted(numbers))
    save_matches(matches)
    return matches


# --- Profixio merges --------------------------------------------------------
# Profixio owns names, numbers, fixtures and official results. Everything the
# user adds here - position, active, video_url, squad, and every recorded
# event - survives a re-sync untouched.

def merge_profixio_roster(players: list) -> pd.DataFrame:
    """Refresh the roster from Profixio, matching players by *name*.

    Shirt numbers change between matches, so keying on the number is wrong in
    two ways at once: a player who switches number gets added a second time,
    and whoever inherits her old number silently takes over her row. Names are
    the stable thing.

    Players no longer in the Profixio squad are kept but deactivated - their
    recorded events still refer to them, and events store the number and name
    as they were at the time, so history is unaffected either way. For everyone
    still in the squad the `active` flag is left exactly as you set it.
    """
    roster = load_roster()
    existing = {}
    for row in roster.to_dict("records"):
        existing.setdefault(str(row["name"]).strip(), row)

    merged, seen = [], set()
    for player in players:
        name = str(player["name"]).strip()
        number = int(player["number"])
        current = existing.get(name)
        seen.add(name)
        if current is None:
            merged.append({
                "player_id": f"p{number}", "number": number, "name": name,
                "position": "", "active": True,
            })
        else:
            # `active` is yours - someone can be in the registered squad and
            # still be injured. A sync only ever changes the number.
            merged.append({**current, "number": number, "name": name})

    for name, row in existing.items():
        if name not in seen:
            merged.append({**row, "active": False})

    save_roster(pd.DataFrame(merged, columns=schema.ROSTER_COLUMNS))
    return load_roster()


def merge_profixio_fixtures(fixtures: list) -> pd.DataFrame:
    matches = load_matches()
    by_profixio_id = {}
    for row in matches.to_dict("records"):
        if row.get("profixio_match_id"):
            by_profixio_id[str(row["profixio_match_id"])] = row

    merged = []
    seen_ids = set()
    for fixture in fixtures:
        profixio_id = str(fixture["profixio_match_id"])
        current = by_profixio_id.get(profixio_id)
        if current is None:
            # Fall back to date+opponent so a hand-created match gets adopted
            # rather than duplicated.
            candidates = matches[
                (matches["date"] == fixture["date"])
                & (matches["opponent"] == fixture["opponent"])
            ]
            current = candidates.iloc[0].to_dict() if len(candidates) else None

        # The match_id is never changed once assigned - events hang off it.
        match_id = (current or {}).get("match_id") or new_match_id(
            fixture["date"], fixture["opponent"]
        )
        merged.append({
            **(current or {}),
            "match_id": match_id,
            "date": fixture["date"],
            "opponent": fixture["opponent"],
            "home_away": fixture["home_away"],
            "profixio_match_id": profixio_id,
            "official_result": fixture["official_result"],
            "official_sets": fixture["official_sets"],
        })
        seen_ids.add(match_id)

    # Matches that are not in Profixio (friendlies, say) are left alone.
    for row in matches.to_dict("records"):
        if row["match_id"] not in seen_ids:
            merged.append(row)

    frame = pd.DataFrame(merged, columns=schema.MATCH_COLUMNS).sort_values(
        "date", ascending=False
    )
    save_matches(frame)
    return load_matches()


def replace_profixio_events(match_id: str, events: list) -> pd.DataFrame:
    """Swap in freshly imported protocol events, leaving manual ones alone."""
    current = load_events()
    imported = (current["match_id"] == match_id) & (
        current["source"] == schema.SOURCE_PROFIXIO
    )
    kept = current[~imported]
    incoming = pd.DataFrame(events, columns=schema.EVENT_COLUMNS)
    if len(incoming):
        incoming["synced"] = False
    save_events(concat_frames([kept, incoming]))
    return load_events()


# --- lineup: who played which role, per set ---------------------------------
# Roles change within a match - a player can set one set and play opposite the
# next - so the grain is (match, set, player). Shirt numbers are per match, and
# are carried on every row of that match's lineup.

def load_lineup() -> pd.DataFrame:
    return _read(LINEUP_FILE, schema.LINEUP_COLUMNS)


def save_lineup(df: pd.DataFrame) -> None:
    _write(df, LINEUP_FILE, schema.LINEUP_COLUMNS)


def set_lineup(match_id: str, set_no: int, rows: list) -> pd.DataFrame:
    """Replace the lineup for one set of one match."""
    lineup = load_lineup()
    others = lineup[
        ~((lineup["match_id"] == match_id) & (lineup["set_no"] == int(set_no)))
    ]
    incoming = pd.DataFrame(
        [
            {**row, "match_id": match_id, "set_no": int(set_no),
             "player_role": schema.normalise_role(
                 row.get("player_role", row.get("role", ""))
             )}
            for row in rows
        ],
        columns=schema.LINEUP_COLUMNS,
    )
    save_lineup(concat_frames([others, incoming]))
    return load_lineup()


def match_lineup(match_id: str, set_no: int = None) -> pd.DataFrame:
    lineup = load_lineup()
    rows = lineup[lineup["match_id"] == match_id]
    if set_no is not None:
        rows = rows[rows["set_no"] == int(set_no)]
    return rows.sort_values(["set_no", "player_num"])


def roles_for_set(match_id: str, set_no: int, inherit: bool = True) -> dict:
    """shirt number -> role for one set.

    Roles carry forward from the last set that set them, which is how a match
    actually works: you write the line-up down once and only note the changes.
    Without this, any set you never opened in the app would blank the roles and
    split a player into two half-rows in the season table.
    """
    for candidate in range(int(set_no), 0, -1):
        rows = match_lineup(match_id, candidate)
        roles = {
            int(row["player_num"]): row["player_role"]
            for row in rows.to_dict("records") if row["player_role"]
        }
        if roles or not inherit:
            return roles
    return {}


def role_of(match_id: str, set_no: int, number, fallback: str = "") -> str:
    return roles_for_set(match_id, set_no).get(int(number), fallback)


def copy_lineup(match_id: str, from_set: int, to_set: int) -> pd.DataFrame:
    """Carry a set's roles forward - most sets start the same as the last."""
    rows = match_lineup(match_id, from_set).to_dict("records")
    return set_lineup(match_id, to_set, [
        {k: row[k] for k in ("player_num", "player_name", "player_role")}
        for row in rows
    ])


def restamp_roles(match_id: str, set_no: int = None) -> pd.DataFrame:
    """Re-apply the lineup to events already recorded.

    Roles are stamped onto events when they are entered, so that the Events tab
    stands on its own. Editing the lineup afterwards therefore has to push the
    change back through - otherwise the two quietly disagree.
    """
    events = load_events()
    target = events["match_id"] == match_id
    if set_no is not None:
        target &= events["set_no"] == int(set_no)
    if not target.any():
        return events

    for set_number in sorted(events.loc[target, "set_no"].unique()):
        roles = roles_for_set(match_id, int(set_number))
        rows = target & (events["set_no"] == set_number)
        events.loc[rows, "player_role"] = events.loc[rows, "player_num"].map(
            lambda number: roles.get(int(number), "")
        )
    save_events(events)
    return events


def protocol_count(match_id: str, set_no: int, number, action: str) -> int:
    """How many of this action the official protocol already has for a player.

    Shown while entering rather than used to block anything: the protocol is
    usually right, but not every match is scored carefully, and a point put
    against the wrong player has to be fixable.
    """
    events = load_events()
    rows = events[
        (events["match_id"] == match_id)
        & (events["set_no"] == int(set_no))
        & (events["player_num"] == int(number))
        & (events["action"] == action)
        & (events["source"] == schema.SOURCE_PROFIXIO)
    ]
    return len(rows)


def has_profixio_events(match_id: str) -> bool:
    """Whether the official protocol has been imported for this match.

    When it has, every point already exists with its scorer, so recording a
    kill or an ace again from video would double count it.
    """
    events = load_events()
    return bool(
        len(events[
            (events["match_id"] == match_id)
            & (events["source"] == schema.SOURCE_PROFIXIO)
        ])
    )


def restore_events(remote: pd.DataFrame) -> dict:
    """Merge events read back from the spreadsheet into the local buffer.

    Additive by `event_id`: rows already here are left exactly as they are, so
    restoring can never overwrite work in progress. Restored rows count as
    synced, because that is where they came from.
    """
    local = load_events()
    if not len(remote):
        return {"added": 0, "already_here": 0, "total": len(local)}

    known = set(local["event_id"]) if len(local) else set()
    fresh = remote[~remote["event_id"].isin(known)].copy()
    if len(fresh):
        fresh["synced"] = True
        save_events(concat_frames([local, fresh]))
    return {
        "added": len(fresh),
        "already_here": len(remote) - len(fresh),
        "total": len(load_events()),
    }


def lineup_from_events(match_id: str, set_no: int) -> list:
    """Who actually appears in a set's recorded events.

    Used to repair a line-up that has fallen behind the events - which happens
    when shirt numbers change and a number-keyed match drops somebody who is
    plainly there in the data.
    """
    events = load_events()
    rows = events[
        (events["match_id"] == match_id) & (events["set_no"] == int(set_no))
    ]
    seen, out = set(), []
    for row in rows.to_dict("records"):
        number = int(row["player_num"])
        if number in seen:
            continue
        seen.add(number)
        out.append({
            "player_num": number,
            "player_name": row["player_name"],
            "player_role": row["player_role"],
        })
    return sorted(out, key=lambda r: r["player_num"])


# --- reconciling what you entered with the official record ------------------

def protocol_score(match_id: str, set_no: int):
    """The official score at the end of a set, or None if there is no protocol.

    When this exists the scoreboard follows it rather than counting along with
    what you record - otherwise correcting one mis-attributed kill also adds a
    point to the set, and the two records drift apart.
    """
    events = load_events()
    rows = events[
        (events["match_id"] == match_id)
        & (events["set_no"] == int(set_no))
        & (events["source"] == schema.SOURCE_PROFIXIO)
    ]
    if not len(rows):
        return None
    return int(rows["score_us"].max()), int(rows["score_them"].max())


def duplicate_candidates(match_id: str, set_no: int) -> pd.DataFrame:
    """Point-scoring events in a set that already has an official protocol.

    Only these can be duplicates: the protocol records nothing else, so a
    reception or a dig you entered cannot collide with it and is never shown.

    Returns both sources together, ordered so a manual event sits next to the
    protocol events it matches, with `matches` counting how many the other
    source holds for the same (player, action, result).
    """
    events = load_events()
    rows = events[
        (events["match_id"] == match_id) & (events["set_no"] == int(set_no))
    ].copy()
    if not len(rows):
        return pd.DataFrame(columns=list(events.columns) + ["matches", "keep"])

    scoring = rows.apply(
        lambda row: schema.is_point(row["action"], row["action_result"]), axis=1
    )
    rows = rows[scoring]
    if schema.SOURCE_PROFIXIO not in set(rows["source"]):
        return rows.iloc[0:0].assign(matches=0, keep=True)

    key = ["player_num", "action", "action_result"]
    counts = rows.groupby(key + ["source"]).size().unstack("source", fill_value=0)

    def other(row):
        wanted = (
            schema.SOURCE_PROFIXIO
            if row["source"] == schema.SOURCE_MANUAL
            else schema.SOURCE_MANUAL
        )
        index = tuple(row[column] for column in key)
        if index not in counts.index or wanted not in counts.columns:
            return 0
        return int(counts.loc[index, wanted])

    rows["matches"] = rows.apply(other, axis=1)
    # The protocol is kept by default; a manual event is kept only when the
    # protocol has nothing like it, which makes it a correction rather than a
    # re-entry of a point that is already there.
    rows["keep"] = (rows["source"] == schema.SOURCE_PROFIXIO) | (rows["matches"] == 0)
    return rows.sort_values(key + ["source"])


def drop_events(event_ids) -> pd.DataFrame:
    events = load_events()
    save_events(events[~events["event_id"].isin(list(event_ids))])
    return load_events()
