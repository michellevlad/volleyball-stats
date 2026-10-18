"""The local buffer is the crash-safety story, so round-tripping it is tested."""

import pandas as pd
import pytest

from volley import schema, store


@pytest.fixture(autouse=True)
def temp_data_dir(temp_store):
    return temp_store


PLAYER = {"player_id": "p7", "number": 7, "name": "Ana"}
MATCH = {"match_id": "m1", "date": "2026-09-26", "opponent": "Lions", "home_away": "home"}


def make_event(match_id="m1", set_no=1, seq=1, action=schema.ATTACK, result="kill", **kwargs):
    return store.build_event(
        match={**MATCH, "match_id": match_id}, set_no=set_no, seq=seq, player=PLAYER,
        action=action, result=result, **kwargs
    )


def test_missing_files_read_as_empty_typed_frames():
    events = store.load_events()
    assert list(events.columns) == store.EVENT_BUFFER_COLUMNS
    assert len(events) == 0
    assert list(store.load_roster().columns) == schema.ROSTER_COLUMNS
    assert list(store.load_matches().columns) == schema.MATCH_COLUMNS


def test_append_persists_and_types_survive_the_round_trip():
    store.append_event(make_event(score_us=5, score_them=3))
    events = store.load_events()
    assert len(events) == 1
    row = events.iloc[0]
    assert row["set_no"] == 1 and isinstance(row["set_no"], (int, pd.Int64Dtype().type))
    assert row["score_us"] == 5 and row["score_them"] == 3
    assert bool(row["is_point"]) is True
    assert row["synced"] == False  # noqa: E712


def test_build_event_rejects_invalid_pairs():
    with pytest.raises(schema.InvalidEvent):
        make_event(action=schema.SERVE, result="kill")


def test_next_seq_counts_per_set():
    store.append_event(make_event(set_no=1, seq=1))
    store.append_event(make_event(set_no=1, seq=2))
    events = store.load_events()
    assert store.next_seq(events, "m1", 1) == 3
    assert store.next_seq(events, "m1", 2) == 1
    assert store.next_seq(events, "other", 1) == 1


def test_delete_and_mark_synced():
    first = make_event(seq=1)
    second = make_event(seq=2, result="error")
    store.append_event(first)
    store.append_event(second)

    store.mark_synced([first["event_id"]])
    events = store.load_events()
    assert len(store.unsynced(events)) == 1
    assert store.unsynced(events).iloc[0]["event_id"] == second["event_id"]

    store.delete_event(second["event_id"])
    assert len(store.load_events()) == 1


def test_current_score_restores_from_the_last_event_of_the_set():
    store.append_event(make_event(set_no=1, seq=1, score_us=1, score_them=0))
    store.append_event(make_event(set_no=1, seq=2, score_us=2, score_them=4))
    store.append_event(make_event(set_no=2, seq=1, score_us=1, score_them=1))
    events = store.load_events()
    assert store.current_score(events, "m1", 1) == (2, 4)
    assert store.current_score(events, "m1", 2) == (1, 1)
    assert store.current_score(events, "m1", 5) == (0, 0)


def test_roster_autofills_player_id_and_filters_inactive():
    roster = pd.DataFrame(
        [
            {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
            {"player_id": "", "number": 3, "name": "Cyd", "position": "S", "active": False},
        ]
    )
    store.save_roster(roster)
    saved = store.load_roster()
    assert set(saved["player_id"]) == {"p7", "p3"}

    active = store.active_players(saved)
    assert list(active["number"]) == [7]
    assert store.find_by_number(saved, 3)["name"] == "Cyd"
    assert store.find_by_number(saved, 99) is None


def test_upsert_match_replaces_rather_than_duplicates():
    base = {
        "match_id": "2026-09-27-lions", "date": "2026-09-27", "opponent": "Lions",
        "home_away": "home", "competition": "", "sets_won": 0, "sets_lost": 0, "notes": "",
    }
    store.upsert_match(base)
    store.upsert_match({**base, "opponent": "Lions B", "sets_won": 3})
    matches = store.load_matches()
    assert len(matches) == 1
    assert matches.iloc[0]["opponent"] == "Lions B"
    assert matches.iloc[0]["sets_won"] == 3


def test_new_match_id_is_slugged():
    assert store.new_match_id("2026-09-27", "AS Lions!") == "2026-09-27-as-lions"


def test_match_events_are_sorted_by_set_then_seq():
    store.append_event(make_event(set_no=2, seq=1))
    store.append_event(make_event(set_no=1, seq=2))
    store.append_event(make_event(set_no=1, seq=1))
    ordered = store.match_events(store.load_events(), "m1")
    assert list(zip(ordered["set_no"], ordered["seq"])) == [(1, 1), (1, 2), (2, 1)]


def test_role_spellings_are_normalised():
    assert schema.normalise_role("OPP") == "OP"
    assert schema.normalise_role("opposite") == "OP"
    assert schema.normalise_role("Middle") == "MB"
    assert schema.normalise_role("lib") == "L"
    assert schema.normalise_role("") == ""
    assert schema.normalise_role("WEIRD") == "WEIRD"   # kept, not discarded


def test_lineup_stores_the_normalised_role():
    store.set_lineup("m1", 1, [
        {"player_num": 9, "player_name": "Dana", "player_role": "OPP"},
    ])
    assert store.role_of("m1", 1, 9) == "OP"


def test_roles_carry_forward_to_sets_that_were_never_set_up():
    store.set_lineup("m1", 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"},
    ])
    assert store.role_of("m1", 1, 7) == "OH"
    assert store.role_of("m1", 3, 7) == "OH"      # inherited, not blank

    store.set_lineup("m1", 3, [
        {"player_num": 7, "player_name": "Ana", "player_role": "MB"},
    ])
    assert store.role_of("m1", 2, 7) == "OH"      # still set 1's
    assert store.role_of("m1", 3, 7) == "MB"      # changed from here
    assert store.role_of("m1", 4, 7) == "MB"      # and carries on


def test_inherit_can_be_turned_off():
    store.set_lineup("m1", 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"},
    ])
    assert store.roles_for_set("m1", 2, inherit=False) == {}


def test_match_name_reads_home_side_first():
    assert store.match_name(
        {"opponent": "Jomala IK C", "home_away": "away"}
    ) == "Jomala IK C vs Elden VBK"
    assert store.match_name(
        {"opponent": "Jomala IK C", "home_away": "home"}
    ) == "Elden VBK vs Jomala IK C"


def test_every_event_carries_the_match_details():
    """The Events tab has to be readable without joining back to Matches."""
    event = make_event()
    assert event["match_date"] == "2026-09-26"
    assert event["match_name"] == "Elden VBK vs Lions"


def test_two_players_cannot_share_a_shirt_in_one_set():
    """A squad recorded in old numbering can collide with the current roster."""
    store.set_lineup("m1", 1, [
        {"player_num": 4, "player_name": "Nadia", "player_role": "OH"},
        {"player_num": 4, "player_name": "Elin", "player_role": "S"},
    ])
    squad = store.squad_players(pd.DataFrame(columns=schema.ROSTER_COLUMNS),
                                {"match_id": "m1"}, 1)
    assert list(squad["number"]) == [4]
    assert list(squad["name"]) == ["Nadia"]


def test_correcting_the_lineup_fixes_names_on_events_already_recorded():
    """A shirt that changed hands between seasons must not rewrite history."""
    store.set_lineup("m1", 1, [
        {"player_num": 4, "player_name": "Elin", "player_role": "S"},
    ])
    store.append_event(make_event(set_no=1, seq=1))
    store.append_event(store.build_event(
        match=MATCH, set_no=1, seq=2,
        player={"player_id": "p4", "number": 4, "name": "Elin"},
        action=schema.ATTACK, result="kill",
    ))
    assert "Elin" in set(store.load_events()["player_name"])

    store.set_lineup("m1", 1, [
        {"player_num": 4, "player_name": "Nadia", "player_role": "S"},
    ])
    store.restamp_players("m1", 1)

    events = store.load_events()
    four = events[events["player_num"] == 4]
    assert set(four["player_name"]) == {"Nadia"}
    # Everyone else is left alone.
    assert set(events[events["player_num"] == 7]["player_name"]) == {"Ana"}


def test_restamping_leaves_a_number_the_lineup_does_not_mention():
    store.set_lineup("m1", 1, [
        {"player_num": 4, "player_name": "Nadia", "player_role": "S"},
    ])
    store.append_event(make_event(set_no=1, seq=1))      # #7 Ana, not in the line-up
    store.restamp_players("m1", 1)
    assert set(store.load_events()["player_name"]) == {"Ana"}


# --- ordering by when it was registered -------------------------------------

MATCH_A = {"match_id": "m1", "date": "2026-09-26", "opponent": "Jomala",
           "home_away": "away"}


def _event(set_no, seq, result, **extra):
    return store.build_event(
        match=MATCH_A, set_no=set_no, seq=seq,
        player={"number": 7, "name": "Ana"},
        action=schema.SERVE, result=result, **extra,
    )


def test_a_new_event_carries_a_registration_stamp(temp_store):
    store.append_event(_event(1, 1, "ace"))
    assert store.load_events().iloc[0]["recorded_at"]


def test_newest_first_follows_the_stamp_not_the_file_order(temp_store):
    """seq restarts each set, so (set, seq) is not the order you worked in."""
    store.append_event(_event(1, 1, "ace", recorded_at="2026-10-18T19:00:00"))
    store.append_event(_event(1, 2, "in", recorded_at="2026-10-18T19:01:00"))
    # Set 2, entered later, but with a lower seq than set 1 reached.
    store.append_event(_event(2, 1, "error", recorded_at="2026-10-18T19:30:00"))

    order = list(store.newest_first(store.load_events(), "m1")["action_result"])
    assert order == ["error", "in", "ace"]


def test_newest_first_survives_the_file_being_rewritten(temp_store):
    """Row order is not a stand-in: saving edits re-appends what it touched."""
    store.append_event(_event(1, 1, "ace", recorded_at="2026-10-18T19:00:00"))
    store.append_event(_event(1, 2, "in", recorded_at="2026-10-18T19:01:00"))

    # Move the oldest row to the end of the file, as a rewrite would.
    events = store.load_events()
    store.save_events(store.concat_frames([events.iloc[1:], events.iloc[:1]]))

    assert store.newest_first(store.load_events(), "m1").iloc[0]["action_result"] == "in"


def test_one_import_shares_one_instant_and_orders_by_seq(temp_store):
    for seq in (1, 2, 3):
        store.append_event(_event(
            1, seq, "ace", source=schema.SOURCE_PROFIXIO,
            recorded_at="2026-10-18T18:00:00",
        ))
    order = list(store.newest_first(store.load_events(), "m1")["seq"])
    assert order == [3, 2, 1]


def test_backfill_orders_the_protocol_before_the_hand_entry(temp_store):
    rows = [
        _event(2, 1, "in"),                                    # entered later
        _event(1, 1, "ace"),                                   # entered first
        _event(1, 1, "error", source=schema.SOURCE_PROFIXIO),  # imported first
    ]
    for row in rows:
        row["recorded_at"] = ""
        store.append_event(row)

    assert store.backfill_recorded_at() == 3
    order = list(store.newest_first(store.load_events(), "m1")["action_result"])
    assert order == ["in", "ace", "error"]


def test_backfill_leaves_stamped_rows_alone_and_is_repeatable(temp_store):
    store.append_event(_event(1, 1, "ace", recorded_at="2020-01-01T00:00:00"))
    blank = _event(1, 2, "in")
    blank["recorded_at"] = ""
    store.append_event(blank)

    assert store.backfill_recorded_at() == 1
    assert store.backfill_recorded_at() == 0      # nothing left to do
    stamps = dict(zip(store.load_events()["action_result"],
                      store.load_events()["recorded_at"]))
    assert stamps["ace"] == "2020-01-01T00:00:00"


def test_mark_reviewed_sticks(temp_store):
    store.append_event(_event(1, 1, "ace"))
    assert bool(store.load_events().iloc[0]["reviewed"]) is False
    store.mark_reviewed(store.load_events()["event_id"])
    assert bool(store.load_events().iloc[0]["reviewed"]) is True


def test_names_for_set_reads_the_lineup(temp_store):
    store.set_lineup("m1", 1, [
        {"player_num": 4, "player_name": "Nadia", "player_role": "S"}])
    assert store.names_for_set("m1", 1) == {4: "Nadia"}
    assert store.names_for_set("m1", 2) == {}
