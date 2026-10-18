"""Metric math checked against a fixture match whose totals are worked out by hand."""

import pandas as pd
import pytest

from volley import schema, stats

MATCH_ID = "2026-09-27-lions"

# (set_no, number, name, action, result)
FIXTURE = [
    # --- #7 Ana, set 1 ---
    (1, 7, "Ana", schema.ATTACK, "kill"),
    (1, 7, "Ana", schema.ATTACK, "kill"),
    (1, 7, "Ana", schema.ATTACK, "error"),
    (1, 7, "Ana", schema.ATTACK, "attempt"),
    (1, 7, "Ana", schema.ATTACK, "attempt"),
    (1, 7, "Ana", schema.SERVE, "ace"),
    (1, 7, "Ana", schema.SERVE, "ace"),
    (1, 7, "Ana", schema.SERVE, "error"),
    (1, 7, "Ana", schema.SERVE, "in"),
    (1, 7, "Ana", schema.SERVE, "in"),
    (1, 7, "Ana", schema.SERVE, "in"),
    (1, 7, "Ana", schema.RECEPTION, "perfect"),
    (1, 7, "Ana", schema.RECEPTION, "perfect"),
    (1, 7, "Ana", schema.RECEPTION, "playable"),
    (1, 7, "Ana", schema.RECEPTION, "playable"),
    (1, 7, "Ana", schema.RECEPTION, "error"),
    (1, 7, "Ana", schema.BLOCK, "kill"),
    (1, 7, "Ana", schema.BLOCK, "attempt"),
    (1, 7, "Ana", schema.BLOCK, "error"),
    (1, 7, "Ana", schema.DIG, "dig"),
    (1, 7, "Ana", schema.DIG, "dig"),
    (1, 7, "Ana", schema.DIG, "dig"),
    (1, 7, "Ana", schema.DIG, "dig"),
    (1, 7, "Ana", schema.DIG, "error"),
    (1, 7, "Ana", schema.SET, "assist"),
    # --- #7 Ana, set 2 (so sets_played is 2) ---
    (2, 7, "Ana", schema.ATTACK, "kill"),
    # --- #12 Bea, set 1 only ---
    (1, 12, "Bea", schema.ATTACK, "kill"),
    (1, 12, "Bea", schema.SET, "assist"),
    (1, 12, "Bea", schema.SET, "assist"),
    (1, 12, "Bea", schema.SET, "assist"),
    (1, 12, "Bea", schema.SET, "assist"),
    (1, 12, "Bea", schema.SET, "assist"),
    (1, 12, "Bea", schema.SET, "error"),
    (1, 12, "Bea", schema.DIG, "dig"),
    (1, 12, "Bea", schema.DIG, "dig"),
]

# Hand-computed from FIXTURE. The stored tabs hold counts only.
ANA = {
    "sets_played": 2,
    "kills": 3,                  # 2 in set 1 + 1 in set 2
    "attack_errors": 1,
    "attempts": 6,               # 3 kills + 1 error + 2 attempts
    "aces": 2,
    "serve_errors": 1,
    "serves": 6,                 # 2 aces + 1 error + 3 in
    "receptions_perfect": 2,
    "receptions_playable": 2,
    "reception_errors": 1,
    "reception_count": 5,
    "blocks": 1,
    "block_errors": 1,
    "block_attempts": 3,         # 1 kill + 1 attempt + 1 error
    "digs": 4,
    "dig_errors": 1,
    "assists": 1,
    "set_errors": 0,
    "set_attempts": 1,
}

# Worked out from those counts, the way Looker will.
ANA_RATES = {
    "kill_pct": 0.5,             # 3 / 6
    "hitting_eff": 0.333,        # (3 - 1) / 6
    "pass_rating": 2.0,          # (3+3+2+2+0) / 5
    "points": 6,                 # 3 kills + 2 aces + 1 block
}

BEA = {
    "sets_played": 1,
    "kills": 1,
    "attack_errors": 0,
    "attempts": 1,
    "aces": 0,
    "serves": 0,
    "reception_count": 0,
    "blocks": 0,
    "digs": 2,
    "assists": 5,
    "set_errors": 1,
    "set_attempts": 6,
}

BEA_RATES = {
    "kill_pct": 1.0,
    "hitting_eff": 1.0,
    "pass_rating": 0.0,          # no receptions must not become NaN or inf
    "points": 1,
}


def build_events(rows, match_id=MATCH_ID, score_fn=None):
    records = []
    for seq, (set_no, number, name, action, result) in enumerate(rows, start=1):
        score_us, score_them = score_fn(set_no, seq) if score_fn else (0, 0)
        records.append(
            {
                "match_id": match_id,
                "match_date": "2026-09-27",
                "match_name": "Elden VBK vs Lions",
                "set_no": set_no,
                "player_num": number,
                "player_name": name,
                "player_role": "",
                "action": action,
                "action_result": result,
                "is_point": schema.is_point(action, result),
                "source": schema.SOURCE_MANUAL,
                "event_id": f"e{seq}",
                "seq": seq,
                "score_us": score_us,
                "score_them": score_them,
            }
        )
    return pd.DataFrame(records, columns=schema.EVENT_COLUMNS)


@pytest.fixture
def events():
    return build_events(FIXTURE)


@pytest.fixture
def matches():
    return pd.DataFrame(
        [
            {
                "match_id": MATCH_ID,
                "date": "2026-09-27",
                "opponent": "Lions",
                "home_away": "home",
                "competition": "League",
                "sets_won": 0,
                "sets_lost": 0,
                "notes": "",
            }
        ],
        columns=schema.MATCH_COLUMNS,
    )


def row_for(frame, number):
    return frame[frame["player_num"] == number].iloc[0]


@pytest.mark.parametrize("metric,expected", sorted(ANA.items()))
def test_player_counts_ana(events, matches, metric, expected):
    ana = row_for(stats.player_match_stats(events, matches), 7)
    assert ana[metric] == expected


@pytest.mark.parametrize("metric,expected", sorted(BEA.items()))
def test_player_counts_bea(events, matches, metric, expected):
    bea = row_for(stats.player_match_stats(events, matches), 12)
    assert bea[metric] == expected


@pytest.mark.parametrize("metric,expected", sorted(ANA_RATES.items()))
def test_player_rates_ana(events, matches, metric, expected):
    ana = row_for(stats.with_rates(stats.player_match_stats(events, matches)), 7)
    assert ana[metric] == pytest.approx(expected, abs=1e-3)


@pytest.mark.parametrize("metric,expected", sorted(BEA_RATES.items()))
def test_player_rates_bea(events, matches, metric, expected):
    bea = row_for(stats.with_rates(stats.player_match_stats(events, matches)), 12)
    assert bea[metric] == pytest.approx(expected, abs=1e-3)


def test_the_stored_tabs_hold_no_rates(events, matches):
    """Rates are Looker's job - a stored one cannot be re-aggregated."""
    stored = stats.player_match_stats(events, matches)
    for rate in ("kill_pct", "hitting_eff", "pass_rating", "points", "block_points"):
        assert rate not in stored.columns
    # ...but the counts they are built from are all there.
    for count in ("kills", "attempts", "attack_errors", "receptions_perfect",
                  "receptions_playable", "reception_count", "aces", "blocks"):
        assert count in stored.columns


def test_rates_survive_being_aggregated_the_right_way(events, matches):
    """SUM(kills)/SUM(attempts) across sets, not the average of per-set rates."""
    per_set = stats.player_set_stats(events)
    ana = per_set[per_set["player_num"] == 7]
    combined = ana["kills"].sum() / ana["attempts"].sum()
    assert combined == pytest.approx(ANA_RATES["kill_pct"], abs=1e-3)
    # The average of the per-set rates is a different, wrong number.
    per_set_rates = stats.with_rates(ana)["kill_pct"]
    assert per_set_rates.mean() != pytest.approx(ANA_RATES["kill_pct"], abs=1e-3)


def test_player_stats_shape_and_match_info(events, matches):
    players = stats.player_match_stats(events, matches)
    assert list(players.columns) == schema.PLAYER_STATS_COLUMNS
    assert len(players) == 2
    assert set(players["match_date"]) == {"2026-09-27"}
    assert set(players["match_name"]) == {"Elden VBK vs Lions"}


def test_team_totals_are_the_sum_of_players(events, matches):
    team = stats.with_rates(stats.team_match_stats(events, matches)).iloc[0]
    assert list(stats.team_match_stats(events, matches).columns) == schema.TEAM_STATS_COLUMNS
    assert team["kills"] == 4
    assert team["attack_errors"] == 1
    assert team["attempts"] == 7
    assert team["kill_pct"] == pytest.approx(4 / 7, abs=1e-3)
    assert team["hitting_eff"] == pytest.approx(3 / 7, abs=1e-3)
    assert team["aces"] == 2
    assert team["serves"] == 6
    assert team["reception_count"] == 5
    assert team["pass_rating"] == pytest.approx(2.0, abs=1e-3)
    assert team["blocks"] == 1
    assert team["digs"] == 6
    assert team["assists"] == 6
    assert team["points"] == pytest.approx(7.0)
    assert team["sets_played"] == 2


def test_set_scores_and_sets_won():
    rows = [
        (1, 7, "Ana", schema.ATTACK, "kill"),
        (1, 7, "Ana", schema.ATTACK, "kill"),
        (2, 7, "Ana", schema.ATTACK, "kill"),
        (2, 7, "Ana", schema.ATTACK, "error"),
        (3, 7, "Ana", schema.ATTACK, "kill"),
    ]
    scores = {1: (25, 20), 2: (18, 25), 3: (15, 13)}

    def score_fn(set_no, seq):
        return scores[set_no]

    team = stats.team_match_stats(build_events(rows, score_fn=score_fn)).iloc[0]
    assert team["set_scores"] == "25-20, 18-25, 15-13"
    assert team["sets_won"] == 2
    assert team["sets_lost"] == 1


def test_empty_input_returns_empty_frames_with_headers():
    empty = pd.DataFrame(columns=schema.EVENT_COLUMNS)
    players = stats.player_match_stats(empty)
    team = stats.team_match_stats(empty)
    assert len(players) == 0 and list(players.columns) == schema.PLAYER_STATS_COLUMNS
    assert len(team) == 0 and list(team.columns) == schema.TEAM_STATS_COLUMNS


def test_unknown_actions_are_ignored(events):
    polluted = pd.concat(
        [events, build_events([(1, 7, "Ana", "TIMEOUT", "x")]).assign(event_id="zz")],
        ignore_index=True,
    )
    ana = row_for(stats.player_match_stats(polluted), 7)
    assert ana["kills"] == ANA["kills"]
    assert ana["attempts"] == ANA["attempts"]


def test_counting_stats_are_integers(events):
    ana = row_for(stats.player_match_stats(events), 7)
    for metric in ("kills", "attempts", "digs", "aces", "reception_count"):
        assert isinstance(ana[metric], (int, pd.Int64Dtype().type)) or float(
            ana[metric]
        ).is_integer()


def test_match_details_come_from_the_events_themselves(events):
    """Every row carries the date and name, so no join back to Matches."""
    players = stats.player_match_stats(events)
    assert list(players.columns) == schema.PLAYER_STATS_COLUMNS
    assert set(players["match_date"]) == {"2026-09-27"}


def test_the_documented_spreadsheet_columns_do_not_drift():
    """The README lists these; a silent change would make it wrong."""
    assert schema.ROSTER_COLUMNS == ["player_id", "number", "name", "position", "active"]
    assert schema.LINEUP_COLUMNS == [
        "match_id", "set_no", "player_num", "player_name", "player_role"
    ]
    # The fields asked for, in the order asked for.
    assert schema.EVENT_COLUMNS[:12] == [
        "match_id", "match_date", "match_name", "set_no",
        "player_num", "player_name", "player_role",
        "action", "action_result", "is_point", "target_num", "source",
    ]
    # ...then the four that make the editor and the per-set check work.
    assert schema.EVENT_COLUMNS[12:] == ["event_id", "seq", "score_us", "score_them"]
    # Players are identified by shirt number, nothing else.
    for columns in (schema.EVENT_COLUMNS, schema.LINEUP_COLUMNS,
                    schema.SET_STATS_COLUMNS):
        assert "player_id" not in columns
    for gone in ("video_seconds", "video_link", "clock", "rotation", "rally_id",
                 "notes", "entered_at"):
        assert gone not in schema.EVENT_COLUMNS

    # The three computed tabs share one set of statistics.
    shared = {
        "kills", "attack_errors", "attempts", "aces", "serve_errors", "serves",
        "receptions_perfect", "receptions_playable", "reception_errors", "reception_count",
        "blocks", "block_attempts", "block_errors", "digs", "dig_errors",
        "assists", "set_attempts", "set_errors",
    }
    for columns in (schema.PLAYER_STATS_COLUMNS, schema.TEAM_STATS_COLUMNS,
                    schema.ROLE_STATS_COLUMNS):
        assert shared <= set(columns)
    assert "player_role" in schema.PLAYER_STATS_COLUMNS
    assert "matches" in schema.ROLE_STATS_COLUMNS
    assert "set_scores" in schema.TEAM_STATS_COLUMNS


# --- per-set grain ----------------------------------------------------------

def test_player_set_stats_is_one_row_per_player_per_set(events):
    per_set = stats.player_set_stats(events)
    assert list(per_set.columns) == schema.SET_STATS_COLUMNS
    # Ana played sets 1 and 2; Bea only set 1.
    assert sorted(per_set[per_set["player_num"] == 7]["set_no"]) == [1, 2]
    assert sorted(per_set[per_set["player_num"] == 12]["set_no"]) == [1]
    assert per_set["set_no"].between(1, 5).all()


def test_the_per_set_rows_sum_to_the_per_match_row(events):
    """Every other player table is this one summed up."""
    per_set = stats.player_set_stats(events)
    per_match = stats.player_match_stats(events)

    for number in (7, 12):
        sets = per_set[per_set["player_num"] == number]
        match = per_match[per_match["player_num"] == number].iloc[0]
        for column in ("kills", "attack_errors", "attempts", "aces", "serve_errors",
                       "serves", "reception_count", "digs", "assists", "blocks"):
            assert sets[column].sum() == match[column], f"{column} for #{number}"


def test_per_set_counts_split_correctly(events):
    per_set = stats.player_set_stats(events)
    ana = per_set[per_set["player_num"] == 7].set_index("set_no")
    assert ana.loc[1, "kills"] == 2 and ana.loc[1, "attempts"] == 5
    assert ana.loc[2, "kills"] == 1 and ana.loc[2, "attempts"] == 1


def test_per_set_carries_the_role_played_in_that_set():
    """The point of the grain: a role change mid-match shows up here first."""
    rows = [
        (1, 7, "Ana", schema.ATTACK, "kill"),
        (2, 7, "Ana", schema.ATTACK, "kill"),
    ]
    frame = build_events(rows)
    frame.loc[frame["set_no"] == 1, "player_role"] = "OH"
    frame.loc[frame["set_no"] == 2, "player_role"] = "MB"

    per_set = stats.player_set_stats(frame).set_index("set_no")
    assert per_set.loc[1, "player_role"] == "OH"
    assert per_set.loc[2, "player_role"] == "MB"


def test_empty_input_gives_an_empty_per_set_table():
    empty = pd.DataFrame(columns=schema.EVENT_COLUMNS)
    out = stats.player_set_stats(empty)
    assert len(out) == 0 and list(out.columns) == schema.SET_STATS_COLUMNS
