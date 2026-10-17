"""Parsers exercised against real recorded Profixio output.

`tests/fixtures/` holds the actual season page and a real Arbetsprotokoll, so
these run offline and against the markup that genuinely ships - not a mock of
what it might look like.
"""

import gzip
from pathlib import Path

import pandas as pd
import pytest

from volley import profixio, schema, stats, store

FIXTURES = Path(__file__).parent / "fixtures"
TEAM = "Elden VBK"

# The recordings are a real season page and a real match protocol, so they name
# actual people - teammates, the opposition and the referees. They are kept out
# of version control; see tests/fixtures/README.md for how to make your own.
pytestmark = pytest.mark.skipif(
    not (FIXTURES / "profixio_team.html.gz").exists()
    or not (FIXTURES / "a_32681384.pdf").exists(),
    reason="Profixio recordings are not in version control (they contain real names)",
)

# The Jomala match, verified by hand against the PDF.
JOMALA = {
    "match_no": "32681384",
    "rows": 110,
    "points_for": 75,      # 3 x 25
    "points_against": 20,  # 9 + 5 + 6
    "result": "3-0",
    "aces": 30,
    "kills": 20,           # 21 Anfall in the log, one of them Jomala's
    "blocks": 2,
    "events": 52,
}


@pytest.fixture(scope="module")
def season_html():
    with gzip.open(FIXTURES / "profixio_team.html.gz", "rt", encoding="utf-8",
                   errors="replace") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def protocol():
    pdf = (FIXTURES / "a_32681384.pdf").read_bytes()
    return profixio.parse_protocol(profixio.extract_pdf_text(pdf))


# --- fixtures ---------------------------------------------------------------

def test_parses_the_whole_season(season_html):
    fixtures = profixio.parse_fixtures(season_html, TEAM)
    assert len(fixtures) == 16
    assert all(f["profixio_match_id"].isdigit() for f in fixtures)
    assert all(f["date"] for f in fixtures)


def test_fixtures_come_back_in_date_order(season_html):
    dates = [f["date"] for f in profixio.parse_fixtures(season_html, TEAM)]
    assert dates == sorted(dates)
    assert dates[0] == "2026-09-26" and dates[-1] == "2027-04-04"


def test_played_matches_carry_the_official_result(season_html):
    fixtures = profixio.parse_fixtures(season_html, TEAM)
    played = [f for f in fixtures if f["played"]]
    assert len(played) == 2

    jomala = next(f for f in played if f["opponent"] == "Jomala IK C")
    assert jomala["profixio_match_id"] == "32681384"
    assert jomala["home_away"] == "away"
    # Profixio prints it home-first (0-3); from our side it is a 3-0 win.
    assert jomala["official_result"] == "3-0"
    assert jomala["official_sets"] == "25-9, 25-5, 25-6"

    sollentuna = next(f for f in played if f["opponent"] == "Sollentuna VK E")
    assert sollentuna["official_result"] == "3-0"
    assert sollentuna["official_sets"] == "25-7, 25-20, 25-18"


def test_unplayed_matches_have_no_result(season_html):
    fixtures = profixio.parse_fixtures(season_html, TEAM)
    upcoming = [f for f in fixtures if not f["played"]]
    assert len(upcoming) == 14
    assert all(f["official_result"] == "" and f["official_sets"] == "" for f in upcoming)


def test_home_and_away_are_from_our_point_of_view(season_html):
    fixtures = profixio.parse_fixtures(season_html, TEAM)
    for fixture in fixtures:
        assert TEAM in (fixture["home"], fixture["away"])
        assert fixture["opponent"] != TEAM
        expected = "home" if fixture["home"] == TEAM else "away"
        assert fixture["home_away"] == expected


def test_parses_the_squad(season_html):
    roster = profixio.parse_roster(season_html)
    assert len(roster) == 11
    numbers = [p["number"] for p in roster]
    assert numbers == sorted(numbers)
    assert numbers == [1, 4, 6, 7, 8, 9, 10, 11, 15, 18, 99]
    by_number = {p["number"]: p["name"] for p in roster}
    assert by_number[1] == "Michelle Rebeca Vlad"
    assert by_number[99] == "Milena Jeczalik"
    assert by_number[15] == "Isadora Labaki Gonçalo"   # non-ASCII survives


# --- the protocol -----------------------------------------------------------

def test_protocol_header(protocol):
    assert protocol["match_no"] == JOMALA["match_no"]
    assert protocol["home"] == "Jomala IK C"
    assert protocol["away"] == TEAM
    assert protocol["date"] == "2026-09-26"
    assert protocol["series"] == "Division 3 Damer"
    # The arena runs straight into the home team with no separator.
    assert protocol["arena"] == "Silverdalshallen, Sollentuna, Sollentuna"


def test_every_logged_row_is_parsed(protocol):
    assert len(protocol["rows"]) == JOMALA["rows"]
    assert [row["row_no"] for row in protocol["rows"]] == list(range(1, 111))


def test_every_scoring_row_is_attributed_to_a_team(protocol):
    unattributed = [
        row for row in protocol["rows"] if row["event"] and not row["team"]
    ]
    assert unattributed == []


def test_set_boundaries_are_recognised(protocol):
    starts = [row["set_start"] for row in protocol["rows"] if row["set_start"]]
    ends = [row["set_end"] for row in protocol["rows"] if row["set_end"]]
    assert starts == [1, 2, 3]
    assert ends == [1, 2]                     # the third set ends the match
    assert sum(1 for row in protocol["rows"] if row["match_end"]) == 1


def test_summary_reconstructs_the_official_result(protocol):
    summary = profixio.protocol_summary(protocol, TEAM)
    assert summary["points_for"] == JOMALA["points_for"]
    assert summary["points_against"] == JOMALA["points_against"]
    assert summary["points_for"] + summary["points_against"] == 95
    assert summary["result"] == JOMALA["result"]


# --- mapping onto our schema ------------------------------------------------

MATCH = {"match_id": "m1", "date": "2026-09-26", "opponent": "Jomala IK C",
         "home_away": "away"}


@pytest.fixture
def events(protocol):
    return profixio.protocol_to_events(protocol, TEAM, MATCH)


def test_only_our_scoring_actions_become_events(events):
    assert len(events) == JOMALA["events"]
    kinds = pd.Series([f"{e['action']}/{e['action_result']}" for e in events]).value_counts()
    assert kinds[f"{schema.SERVE}/ace"] == JOMALA["aces"]
    assert kinds[f"{schema.ATTACK}/kill"] == JOMALA["kills"]
    assert kinds[f"{schema.BLOCK}/kill"] == JOMALA["blocks"]


def test_opponent_errors_move_the_score_but_belong_to_nobody(events, protocol):
    """23 of our 75 points came from opponent errors - they have no scorer."""
    assert JOMALA["points_for"] - len(events) == 23
    assert all(event["player_num"] for event in events)


def test_scores_are_flipped_for_the_away_side(events):
    """Profixio prints home-away; we were away and won every set."""
    last = events[-1]
    assert (last["score_us"], last["score_them"]) == (25, 6)
    assert all(e["score_us"] >= e["score_them"] for e in events)


def test_set_tally_rows_are_not_read_as_points(events):
    """`0-1 1:a set är slut` is a set tally, not a 0-1 scoreline."""
    for event in events:
        assert event["score_us"] <= 25 and event["score_them"] <= 25
        assert not (event["score_us"] <= 3 and event["seq"] > 20)


def test_events_are_numbered_per_set(events):
    by_set = {}
    for event in events:
        by_set.setdefault(event["set_no"], []).append(event["seq"])
    assert sorted(by_set) == [1, 2, 3]
    for seqs in by_set.values():
        assert seqs == list(range(1, len(seqs) + 1))


def test_event_ids_are_deterministic(protocol):
    first = profixio.protocol_to_events(protocol, TEAM, MATCH)
    again = profixio.protocol_to_events(protocol, TEAM, MATCH)
    assert [e["event_id"] for e in first] == [e["event_id"] for e in again]
    assert first[0]["event_id"].startswith(f"pfx-{JOMALA['match_no']}-")


def test_imported_events_are_tagged_as_imported(events):
    assert all(e["source"] == schema.SOURCE_PROFIXIO for e in events)
    assert all(e["match_name"] == "Jomala IK C vs Elden VBK" for e in events)
    assert all(e["match_date"] == "2026-09-26" for e in events)


def test_the_roster_name_wins_over_the_protocol_spelling(protocol):
    roster = pd.DataFrame(
        [{"player_id": "p99", "number": 99, "name": "Milena J", "position": "OH",
          "active": True}],
        columns=schema.ROSTER_COLUMNS,
    )
    events = profixio.protocol_to_events(protocol, TEAM, MATCH, roster)
    milena = next(e for e in events if e["player_num"] == 99)
    assert milena["player_name"] == "Milena J"
    # Anyone not on the roster keeps the name the protocol gave them.
    other = next(e for e in events if e["player_num"] != 99)
    assert other["player_name"]


def test_the_box_score_matches_the_official_sets(events):
    frame = pd.DataFrame(events, columns=schema.EVENT_COLUMNS)
    team = stats.with_rates(stats.team_match_stats(frame)).iloc[0]
    assert team["set_scores"] == "25-9, 25-5, 25-6"
    assert (int(team["sets_won"]), int(team["sets_lost"])) == (3, 0)
    assert team["points"] == JOMALA["events"]


def test_a_protocol_for_another_team_yields_nothing(protocol):
    assert profixio.protocol_to_events(protocol, "Some Other VBK", MATCH) == []


# --- import is idempotent and never touches manual work ---------------------

def test_reimport_replaces_only_imported_events(temp_store, events):
    manual = store.build_event(
        match=MATCH, set_no=1, seq=1,
        player={"player_id": "p7", "number": 7, "name": "Canan"},
        action=schema.RECEPTION, result="perfect",
    )
    store.append_event(manual)
    store.replace_profixio_events("m1", events)
    assert len(store.load_events()) == len(events) + 1

    store.replace_profixio_events("m1", events)
    after = store.load_events()
    assert len(after) == len(events) + 1
    assert after["event_id"].duplicated().sum() == 0
    survivor = after[after["source"] == schema.SOURCE_MANUAL]
    assert len(survivor) == 1 and survivor.iloc[0]["event_id"] == manual["event_id"]


def test_import_does_not_touch_other_matches(temp_store, events):
    other = store.build_event(
        match={**MATCH, "match_id": "m2"}, set_no=1, seq=1,
        player={"player_id": "p7", "number": 7, "name": "Canan"},
        action=schema.DIG, result="dig",
    )
    store.append_event(other)
    store.replace_profixio_events("m1", events)
    assert len(store.load_events()[store.load_events()["match_id"] == "m2"]) == 1


def test_imported_events_are_queued_for_pushing(temp_store, events):
    store.replace_profixio_events("m1", events)
    assert len(store.unsynced(store.load_events())) == len(events)


# --- season merge -----------------------------------------------------------

def test_merging_fixtures_preserves_local_work(temp_store, season_html):
    fixtures = profixio.parse_fixtures(season_html, TEAM)
    store.merge_profixio_fixtures(fixtures)
    matches = store.load_matches()
    assert len(matches) == 16

    match_id = matches.iloc[0]["match_id"]
    store.upsert_match({**matches.iloc[0].to_dict(), "video_url": "https://youtu.be/abc",
                        "squad": "1,7,99"})

    store.merge_profixio_fixtures(fixtures)           # re-sync
    again = store.load_matches()
    assert len(again) == 16
    row = again[again["match_id"] == match_id].iloc[0]
    assert row["video_url"] == "https://youtu.be/abc"
    assert row["squad"] == "1,7,99"


def test_merging_the_roster_preserves_position_and_active(temp_store, season_html):
    players = profixio.parse_roster(season_html)
    store.merge_profixio_roster(players)
    roster = store.load_roster()
    assert len(roster) == 11

    roster.loc[roster["number"] == 1, "position"] = "S"
    roster.loc[roster["number"] == 4, "active"] = False
    store.save_roster(roster)

    store.merge_profixio_roster(players)              # re-sync
    again = store.load_roster()
    assert again[again["number"] == 1].iloc[0]["position"] == "S"
    assert bool(again[again["number"] == 4].iloc[0]["active"]) is False
    assert len(again) == 11


def test_players_dropped_from_profixio_are_kept_but_deactivated(temp_store, season_html):
    """Deleting them would orphan every event they appear in."""
    players = profixio.parse_roster(season_html)
    store.merge_profixio_roster(players)
    store.merge_profixio_roster(players[:3])

    roster = store.load_roster()
    assert len(roster) == 11
    assert roster["active"].sum() == 3
    # ...and they stay out of the default call-up.
    assert len(store.active_players(roster)) == 3


def test_a_changed_shirt_number_updates_the_player(temp_store):
    """Numbers move between matches; the player is the same person."""
    store.merge_profixio_roster([{"number": 99, "name": "Milena Jeczalik"}])
    store.save_roster(store.load_roster().assign(position="MB"))

    store.merge_profixio_roster([{"number": 31, "name": "Milena Jeczalik"}])
    roster = store.load_roster()
    assert len(roster) == 1
    assert int(roster.iloc[0]["number"]) == 31
    assert roster.iloc[0]["position"] == "MB"      # local edits survive


def test_a_number_handed_to_someone_else_does_not_rename_anyone(temp_store):
    """Luisa moved 4 -> 17 and Maryam took 4. Two players, not one renamed."""
    store.merge_profixio_roster([{"number": 4, "name": "Luisa Velez Ledesma"}])
    store.merge_profixio_roster([
        {"number": 17, "name": "Luisa Velez Ledesma"},
        {"number": 4, "name": "Maryam Al-saqa"},
    ])
    roster = store.load_roster()
    by_name = {r["name"]: int(r["number"]) for r in roster.to_dict("records")}
    assert by_name == {"Luisa Velez Ledesma": 17, "Maryam Al-saqa": 4}
    assert len(roster) == 2


def test_a_sync_never_overrides_your_own_active_flag(temp_store):
    """Someone can be in the registered squad and still be injured."""
    store.merge_profixio_roster([{"number": 18, "name": "Kira Zhukova"}])
    roster = store.load_roster()
    roster["active"] = False
    store.save_roster(roster)

    store.merge_profixio_roster([{"number": 18, "name": "Kira Zhukova"}])
    assert bool(store.load_roster().iloc[0]["active"]) is False


# --- the protocol download is behind a bot check ----------------------------

def test_finds_an_already_downloaded_protocol(tmp_path):
    (tmp_path / "a_32681384.pdf").write_bytes(b"%PDF-1.7 ...")
    found = profixio.find_downloaded_protocol("32681384", [tmp_path])
    assert found is not None and found.name == "a_32681384.pdf"
    assert profixio.find_downloaded_protocol("99999", [tmp_path]) is None


def test_reading_a_non_pdf_is_a_readable_error(tmp_path):
    bad = tmp_path / "a_1.pdf"
    bad.write_bytes(b"<html>Just a moment...")
    with pytest.raises(profixio.ProfixioError, match="not a PDF"):
        profixio.read_protocol_file(bad)


def test_protocol_url_shape():
    assert profixio.protocol_url("111", "222").endswith(
        "/app/leagueid111/match/222/protocol/svbf_a"
    )


def test_team_url_shape():
    assert profixio.team_url("111", "222", "333") == (
        "https://www.profixio.com/app/leagueid111/teams/222?k=333"
    )


# --- the command line uses the same call as the app -------------------------

def test_the_sync_cli_passes_a_match_row_not_an_id(temp_store, protocol, monkeypatch):
    """The CLI once passed the id and broke on the first import after a sync."""
    import sync_profixio

    store.upsert_match({**MATCH, "profixio_match_id": "32681384"})
    monkeypatch.setattr(profixio, "find_downloaded_protocol", lambda *a, **k: "fake.pdf")
    monkeypatch.setattr(profixio, "read_protocol_file", lambda path: b"%PDF")
    monkeypatch.setattr(profixio, "extract_pdf_text", lambda data: "")
    monkeypatch.setattr(profixio, "parse_protocol", lambda text: protocol)

    assert sync_profixio.import_protocol("32681384") == 52
    saved = store.load_events()
    assert len(saved) == 52
    assert set(saved["match_name"]) == {"Jomala IK C vs Elden VBK"}
    assert set(saved["match_date"]) == {"2026-09-26"}
