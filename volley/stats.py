"""pandas aggregations: raw events -> box score.

Every metric definition lives here rather than in Looker Studio formulas, so
the numbers are testable and there is exactly one place to change them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema


# Reception ratings, for the app's own display only. The spreadsheet stores
# the counts and Looker does the arithmetic.
RECEPTION_WEIGHTS = schema.RECEPTION_VALUES


def _ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Safe division: 0 attempts gives 0, not inf or NaN."""
    return (numerator / denominator.replace(0, np.nan)).fillna(0).round(3)


def with_rates(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the derived rates, for showing on screen.

    Deliberately not stored: these are calculated fields in Looker so that they
    stay correct at whatever grain a chart aggregates to.
    """
    out = frame.copy()
    if not len(out):
        for column in ("kill_pct", "hitting_eff", "pass_rating", "points"):
            out[column] = []
        return out
    out["kill_pct"] = _ratio(out["kills"], out["attempts"])
    out["hitting_eff"] = _ratio(out["kills"] - out["attack_errors"], out["attempts"])
    out["pass_rating"] = _ratio(
        RECEPTION_WEIGHTS["perfect"] * out["receptions_perfect"]
        + RECEPTION_WEIGHTS["playable"] * out["receptions_playable"],
        out["reception_count"],
    )
    out["points"] = out["kills"] + out["aces"] + out["blocks"]
    return out


def _aggregate(events: pd.DataFrame, index_cols: list[str]) -> pd.DataFrame:
    """Count every action/result pair and derive the standard box-score metrics."""
    ev = events.copy()
    ev = ev[ev["action"].isin(schema.ACTIONS)]
    if not len(ev):
        return pd.DataFrame()

    ev["key"] = ev["action"].astype(str) + "|" + ev["action_result"].astype(str)
    counts = ev.groupby(index_cols + ["key"]).size().unstack("key", fill_value=0)

    def col(key: str) -> pd.Series:
        if key in counts.columns:
            return counts[key].astype(float)
        return pd.Series(0.0, index=counts.index)

    kills = col("ATTACK|kill")
    attack_errors = col("ATTACK|error")
    attempts = kills + attack_errors + col("ATTACK|attempt")

    aces = col("SERVE|ace")
    serve_errors = col("SERVE|error")
    serves = aces + serve_errors + col("SERVE|in")

    perfect = col("RECEPTION|perfect")
    playable = col("RECEPTION|playable")
    reception_errors = col("RECEPTION|error")

    out = pd.DataFrame(index=counts.index)
    out["sets_played"] = ev.groupby(index_cols)["set_no"].nunique()
    out["kills"] = kills
    out["attack_errors"] = attack_errors
    out["attempts"] = attempts
    out["aces"] = aces
    out["serve_errors"] = serve_errors
    out["serves"] = serves
    out["receptions_perfect"] = perfect
    out["receptions_playable"] = playable
    out["reception_errors"] = reception_errors
    out["reception_count"] = perfect + playable + reception_errors
    out["blocks"] = col("BLOCK|kill")
    out["block_errors"] = col("BLOCK|error")
    out["block_attempts"] = col("BLOCK|kill") + col("BLOCK|error") + col("BLOCK|attempt")
    out["digs"] = col("DIG|dig")
    out["dig_errors"] = col("DIG|error")
    out["assists"] = col("SET|assist")
    out["set_errors"] = col("SET|error")
    out["set_attempts"] = col("SET|assist") + col("SET|error") + col("SET|attempt")

    # Counting stats stay integers; only the three rates and block_points are fractional.
    return out.astype(int).reset_index()


def _attach_match_info(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Every event carries the match date and name, so no join is needed."""
    info = (
        events[["match_id", "match_date", "match_name"]]
        .drop_duplicates("match_id")
        .fillna("")
    )
    return df.merge(info, on="match_id", how="left").fillna({"match_date": "", "match_name": ""})


def _with_role(events: pd.DataFrame) -> pd.DataFrame:
    """Guarantee a role column, so grouping works on older data too."""
    frame = events.copy()
    if "player_role" not in frame.columns:
        frame["player_role"] = ""
    frame["player_role"] = frame["player_role"].fillna("").astype(str)
    return frame


def player_match_stats(
    events: pd.DataFrame, matches: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per player per match *per role*.

    A player who sets one set and plays opposite the next gets two rows for
    that match - which is the whole point: their numbers in each role stay
    separate instead of being averaged into one meaningless line.
    """
    events = _with_role(events)
    keys = ["match_id", "player_num", "player_role"]
    out = _aggregate(events, keys)
    if not len(out):
        return pd.DataFrame(columns=schema.PLAYER_STATS_COLUMNS)

    identity = events.groupby(keys)[["player_name"]].last().reset_index()
    out = out.merge(identity, on=keys, how="left")
    out = _attach_match_info(out, events)
    out = out[schema.PLAYER_STATS_COLUMNS]
    return out.sort_values(
        ["match_date", "match_id", "player_num", "player_role"]
    ).reset_index(drop=True)


def player_set_stats(events: pd.DataFrame) -> pd.DataFrame:
    """One row per player per set - the finest grain the events support.

    Every other player table is this summed up, so if a number ever looks wrong
    somewhere else, this is where to check it.
    """
    events = _with_role(events)
    keys = ["match_id", "set_no", "player_num", "player_role"]
    out = _aggregate(events, keys)
    if not len(out):
        return pd.DataFrame(columns=schema.SET_STATS_COLUMNS)

    identity = events.groupby(keys)[["player_name"]].last().reset_index()
    out = out.merge(identity, on=keys, how="left")
    out = _attach_match_info(out, events)
    out = out[schema.SET_STATS_COLUMNS]
    return out.sort_values(
        ["match_date", "match_id", "set_no", "player_num"]
    ).reset_index(drop=True)


def player_role_stats(events: pd.DataFrame) -> pd.DataFrame:
    """Season totals per player per role.

    Rates are recomputed from the raw counts rather than averaged across
    matches - averaging a hitting efficiency is one of the classic ways to get
    a wrong number.
    """
    events = _with_role(events)
    keys = ["player_num", "player_role"]
    out = _aggregate(events, keys)
    if not len(out):
        return pd.DataFrame(columns=schema.ROLE_STATS_COLUMNS)

    identity = events.groupby(keys)[["player_name"]].last().reset_index()
    played = events.groupby(keys)["match_id"].nunique().rename("matches").reset_index()
    out = out.merge(identity, on=keys, how="left").merge(played, on=keys, how="left")
    out = out[schema.ROLE_STATS_COLUMNS]
    return out.sort_values(["player_num", "player_role"]).reset_index(drop=True)


def per_set_scores(events: pd.DataFrame) -> pd.DataFrame:
    """The score at the end of each set, from the running score on each event."""
    if not len(events):
        return pd.DataFrame(columns=["match_id", "set_no", "score_us", "score_them"])
    frame = (
        events.groupby(["match_id", "set_no"])[["score_us", "score_them"]]
        .max()
        .reset_index()
        .sort_values(["match_id", "set_no"])
    )
    for column in ("set_no", "score_us", "score_them"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    return frame


def _set_scores(events: pd.DataFrame) -> pd.DataFrame:
    """Final score per set, taken from the running score stamped on each event."""
    per_set = (
        events.groupby(["match_id", "set_no"])[["score_us", "score_them"]]
        .max()
        .reset_index()
        .sort_values(["match_id", "set_no"])
    )
    per_set["label"] = (
        per_set["score_us"].astype(int).astype(str)
        + "-"
        + per_set["score_them"].astype(int).astype(str)
    )
    per_set["won"] = (per_set["score_us"] > per_set["score_them"]).astype(int)
    per_set["lost"] = (per_set["score_us"] < per_set["score_them"]).astype(int)
    return (
        per_set.groupby("match_id")
        .agg(
            set_scores=("label", ", ".join),
            sets_won=("won", "sum"),
            sets_lost=("lost", "sum"),
        )
        .reset_index()
    )


def team_match_stats(
    events: pd.DataFrame, matches: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per match, our team's totals."""
    out = _aggregate(events, ["match_id"])
    if not len(out):
        return pd.DataFrame(columns=schema.TEAM_STATS_COLUMNS)

    out = out.merge(_set_scores(events), on="match_id", how="left")
    out = _attach_match_info(out, events)
    out = out[schema.TEAM_STATS_COLUMNS]
    return out.sort_values(["match_date", "match_id"]).reset_index(drop=True)
