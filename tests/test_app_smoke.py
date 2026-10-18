"""End-to-end: run the real Streamlit script and drive it like a user would.

Streamlit reruns the whole script on every interaction, so a smoke test that
actually clicks is the only way to catch session-state and callback mistakes.
"""

import base64
from pathlib import Path

import pandas as pd
import pytest

from volley import schema, store, video

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

# Streamlit 1.66 resolves a relative script path against the file that calls
# from_file, not the working directory, so this has to be absolute.
APP = str(Path(__file__).resolve().parent.parent / "app.py")

VIDEO_URL = "https://youtu.be/dQw4w9WgXcQ"

def offline(app):
    """Stop the app auto-connecting to Google during a test."""
    app.session_state["connect_attempted"] = True
    return app


def record(app, number, action, result, target=None):
    """Record one event the only way there is now: action, result, player."""
    app.button(key=f"action::{action}").click().run()
    app.button(key=f"result::{action}::{result}").click().run()
    app.button(key=f"player::p{number}").click().run()
    if target is not None:                      # an assist needs a fourth tap
        app.button(key=f"target::p{target}").click().run()
    return app


def squad_table(app, rows, match_id=None):
    """Stand in for the squad data editor, which AppTest cannot click."""
    app.session_state[f"squad_edit::{match_id or MATCH['match_id']}"] = pd.DataFrame(
        rows, columns=["called", "player_num", "player_name", "player_role"]
    )
    return app


def past_setup(app, match_id=None):
    """Start on the entry workspace rather than the match-setup gate."""
    offline(app)
    match_id = match_id or MATCH["match_id"]
    app.session_state["match_id"] = match_id
    app.session_state["setup_done_for"] = match_id
    return app


MATCH = {
    "match_id": "2026-09-27-lions", "date": "2026-09-27", "opponent": "Lions",
    "home_away": "home", "competition": "League", "sets_won": 0, "sets_lost": 0,
    "video_url": VIDEO_URL, "notes": "",
}


@pytest.fixture
def app(temp_store, monkeypatch):
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
        {"player_id": "", "number": 12, "name": "Bea", "position": "S", "active": True},
    ]))
    store.upsert_match(MATCH)
    return past_setup(AppTest.from_file(APP, default_timeout=30)).run()


def test_app_renders_without_exceptions(app):
    assert not app.exception
    assert any("Volleyball Stats" in title.value for title in app.title)


def test_three_clicks_record_an_event_and_bump_the_score(app):
    app.button(key=f"action::{schema.ATTACK}").click().run()
    assert not app.exception
    app.button(key=f"result::{schema.ATTACK}::kill").click().run()
    assert not app.exception
    app.button(key="player::p7").click().run()
    assert not app.exception

    events = store.load_events()
    assert len(events) == 1
    row = events.iloc[0]
    assert (row["player_num"], row["action"], row["action_result"]) == (7, schema.ATTACK, "kill")
    assert row["score_us"] == 1          # a kill is a point
    assert row["score_them"] == 0
    assert row["synced"] == False        # noqa: E712 - nothing pushed yet

    # Selection resets so the next event starts from the action row again.
    assert app.session_state["sel_action"] is None
    assert app.session_state["sel_result"] is None
    assert app.session_state["sel_player"] is None


def test_undo_removes_the_last_event(app):
    record(app, 7, schema.ATTACK, "kill")
    event_id = store.load_events().iloc[0]["event_id"]
    app.button(key=f"undo::{event_id}").click().run()
    assert not app.exception
    assert len(store.load_events()) == 0


def test_opponent_point_button_moves_only_their_score(app):
    them_key = f"score_them::{MATCH['match_id']}::1"
    app.button(key=f"bump::{them_key}").click().run()
    assert not app.exception
    assert app.session_state[them_key] == 1
    record(app, 7, schema.ATTACK, "kill")
    row = store.load_events().iloc[0]
    assert (row["score_us"], row["score_them"]) == (1, 1)


def test_score_is_restored_from_the_buffer_on_a_fresh_session(app):
    record(app, 7, schema.ATTACK, "kill")
    record(app, 7, schema.SERVE, "ace")
    assert store.load_events().iloc[-1]["score_us"] == 2

    restarted = past_setup(AppTest.from_file(APP, default_timeout=30))
    restarted.run()
    assert not restarted.exception
    assert restarted.session_state[f"score_us::{MATCH['match_id']}::1"] == 2


def test_box_score_appears_once_events_exist(app):
    for number, action, result in (
        (7, schema.ATTACK, "kill"),
        (7, schema.ATTACK, "error"),
        (7, schema.ATTACK, "attempt"),
        (12, schema.RECEPTION, "perfect"),
    ):
        record(app, number, action, result)
    assert not app.exception
    assert any("Box score" in header.value for header in app.subheader)
    assert len(app.dataframe) >= 1


# --- video panel ------------------------------------------------------------

@pytest.fixture
def app_with_video(temp_store, monkeypatch):
    """Drive the app with a canned component payload.

    The real panel lives in an iframe that AppTest cannot click, so the
    component boundary is stubbed and the Python side of the contract - which
    is where the interesting bugs are - is exercised for real.
    """
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
    ]))
    store.upsert_match(MATCH)

    box = {"payload": None}
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: box["payload"])
    return past_setup(AppTest.from_file(APP, default_timeout=30)), box


def test_events_are_still_recorded_with_no_video_linked(temp_store, monkeypatch):
    """The video is an aid, not a dependency - entry must work without it."""
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
    ]))
    store.upsert_match({**MATCH, "video_url": ""})
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)

    app = past_setup(AppTest.from_file(APP, default_timeout=30)).run()
    record(app, 7, schema.ATTACK, "kill")
    assert not app.exception

    events = store.load_events()
    assert len(events) == 1
    assert events.iloc[0]["match_name"] == "Elden VBK vs Lions"


# --- branding ---------------------------------------------------------------

# A 1x1 transparent PNG, enough for Streamlit to render an image element.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def blank_app(temp_store, monkeypatch):
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)
    return temp_store, monkeypatch


def test_runs_without_a_logo_file(blank_app):
    tmp_path, monkeypatch = blank_app
    monkeypatch.setenv("VOLLEY_LOGO", str(tmp_path / "missing.png"))
    app = offline(AppTest.from_file(APP, default_timeout=30)).run()
    assert not app.exception
    assert any("Elden VBK" in title.value for title in app.title)


def test_renders_the_logo_when_the_file_is_there(blank_app):
    tmp_path, monkeypatch = blank_app
    logo = tmp_path / "elden-vbk.png"
    logo.write_bytes(TINY_PNG)
    monkeypatch.setenv("VOLLEY_LOGO", str(logo))
    app = offline(AppTest.from_file(APP, default_timeout=30)).run()
    assert not app.exception
    assert any("Elden VBK" in title.value for title in app.title)


# --- the match-setup gate ---------------------------------------------------

@pytest.fixture
def gated_app(temp_store, monkeypatch):
    """A configured match that has NOT been through setup yet."""
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
        {"player_id": "", "number": 12, "name": "Bea", "position": "S", "active": True},
        {"player_id": "", "number": 4, "name": "Cyd", "position": "MB", "active": True},
    ]))
    store.upsert_match({**MATCH, "official_result": "3-0",
                        "official_sets": "25-9, 25-5, 25-6"})
    app = offline(AppTest.from_file(APP, default_timeout=30))
    app.session_state["match_id"] = MATCH["match_id"]
    return app.run()


def test_setup_blocks_the_workspace_until_confirmed(gated_app):
    assert not gated_app.exception
    assert any("Match setup" in s.value for s in gated_app.subheader)
    # The entry surface is not reachable yet.
    with pytest.raises(KeyError):
        gated_app.button(key=f"action::{schema.ATTACK}")


def test_starting_entry_opens_the_workspace_and_saves_the_squad(gated_app):
    squad_table(gated_app, [
        (True, 4, "Cyd", "MB"),
        (True, 7, "Ana", "OH"),
        (False, 12, "Bea", "S"),
    ])
    gated_app.button(key="start_entering").click().run()
    assert not gated_app.exception

    assert gated_app.session_state["setup_done_for"] == MATCH["match_id"]
    gated_app.button(key=f"action::{schema.ATTACK}").click().run()
    gated_app.button(key=f"result::{schema.ATTACK}::kill").click().run()
    assert gated_app.button(key="player::p7") is not None
    match = store.load_matches().iloc[0].to_dict()
    assert store.squad_numbers(match) == [4, 7]


def test_the_squad_filters_the_player_grid(gated_app):
    squad_table(gated_app, [
        (True, 4, "Cyd", "MB"),
        (True, 7, "Ana", "OH"),
        (False, 12, "Bea", "S"),
    ])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key=f"action::{schema.ATTACK}").click().run()
    gated_app.button(key=f"result::{schema.ATTACK}::kill").click().run()

    keys = [b.key for b in gated_app.button if b.key.startswith("player::")]
    assert keys == ["player::p4", "player::p7"]


def test_the_shirt_number_can_differ_from_the_roster(gated_app):
    """Numbers belong to a match: Profixio reassigns them and shirts get lent."""
    squad_table(gated_app, [(True, 77, "Ana", "OH")])
    gated_app.button(key="start_entering").click().run()
    assert not gated_app.exception

    record(gated_app, 77, schema.ATTACK, "attempt")
    row = store.load_events().iloc[-1]
    assert int(row["player_num"]) == 77 and row["player_name"] == "Ana"


def test_the_role_set_in_the_squad_table_reaches_the_events(gated_app):
    squad_table(gated_app, [(True, 7, "Ana", "OP")])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert store.load_events().iloc[-1]["player_role"] == "OP"


def test_the_official_result_is_shown_on_setup(gated_app):
    text = " ".join(m.value for m in gated_app.markdown)
    assert "3-0" in text and "25-9" in text


def test_setup_can_be_reopened_from_the_sidebar(gated_app):
    gated_app.button(key="start_entering").click().run()
    assert gated_app.session_state["setup_done_for"] == MATCH["match_id"]
    gated_app.button(key="reopen_setup").click().run()
    assert not gated_app.exception
    assert gated_app.session_state["setup_done_for"] == ""
    assert any("Match setup" in s.value for s in gated_app.subheader)


def test_an_expired_token_shows_the_command_not_a_stack_trace(gated_app, monkeypatch):
    from volley import sheets

    def expired(*args, **kwargs):
        raise sheets.SheetsError(sheets.REAUTH_HINT, sheets.REAUTH_COMMAND)

    monkeypatch.setattr(sheets, "get_client", expired)
    gated_app.session_state["connect_attempted"] = False
    gated_app.run()

    assert not gated_app.exception
    assert any("expired" in e.value for e in gated_app.error)
    assert any("gcloud auth application-default login" in c.value for c in gated_app.code)


def test_a_protocol_only_box_score_says_so(gated_app):
    """Hitting efficiency of 1.000 must not read as a real number."""
    from volley import profixio
    from pathlib import Path

    protocol = profixio.parse_protocol(
        profixio.extract_pdf_text(
            (Path(__file__).parent / "fixtures" / "a_32681384.pdf").read_bytes()
        )
    )
    events = profixio.protocol_to_events(protocol, "Elden VBK", MATCH)
    store.replace_profixio_events(MATCH["match_id"], events)

    gated_app.button(key="start_entering").click().run()
    assert not gated_app.exception
    assert any("Official protocol only" in i.value for i in gated_app.info)

    # One video-entered event and the caveat is no longer true.
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert not any("Official protocol only" in i.value for i in gated_app.info)


# --- the protocol informs, it does not block ---------------------------------

def import_jomala_protocol(match_id):
    from pathlib import Path

    from volley import profixio

    protocol = profixio.parse_protocol(
        profixio.extract_pdf_text(
            (Path(__file__).parent / "fixtures" / "a_32681384.pdf").read_bytes()
        )
    )
    match = store.load_matches().iloc[0].to_dict()
    events = profixio.protocol_to_events(protocol, "Elden VBK", match)
    store.replace_profixio_events(match_id, events)
    return events


needs_protocol = pytest.mark.skipif(
    not (Path(__file__).parent / "fixtures" / "a_32681384.pdf").exists(),
    reason="Profixio recording is not in version control",
)


@needs_protocol
def test_scoring_actions_stay_available_with_a_protocol_imported(gated_app):
    """Not every match is scored carefully; a wrong point has to be fixable."""
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key=f"action::{schema.ATTACK}").click().run()

    for result in schema.ACTIONS[schema.ATTACK]:
        assert gated_app.button(key=f"result::{schema.ATTACK}::{result}").disabled is False


@needs_protocol
def test_a_manually_added_kill_is_recorded(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    before = len(store.load_events())
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.ATTACK, "kill")
    assert not gated_app.exception

    after = store.load_events()
    assert len(after) == before + 1
    added = after.iloc[-1]
    assert added["action_result"] == "kill"
    assert added["source"] == schema.SOURCE_MANUAL


@needs_protocol
def test_what_the_protocol_already_holds_is_shown(gated_app):
    """Informational, so you can tell a correction from a duplicate."""
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key=f"action::{schema.SERVE}").click().run()
    gated_app.button(key=f"result::{schema.SERVE}::ace").click().run()

    # Before the player row, so it can stop a double entry rather than report
    # one that has already happened.
    captions = " ".join(c.value for c in gated_app.caption)
    assert "official protocol already has" in captions
    assert "#7" in captions
    assert "player::p7" in [b.key for b in gated_app.button]


def test_nothing_is_said_when_there_is_no_protocol(gated_app):
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key=f"action::{schema.ATTACK}").click().run()
    gated_app.button(key=f"result::{schema.ATTACK}::kill").click().run()
    assert not any("official protocol already has" in c.value for c in gated_app.caption)

    before = len(store.load_events())
    record(gated_app, 7, schema.ATTACK, "kill")
    assert len(store.load_events()) == before + 1


# --- roles per set ----------------------------------------------------------

def test_roles_default_from_the_roster_and_carry_forward(gated_app):
    from volley import store as s

    roster = s.load_roster()
    roster.loc[roster["number"] == 7, "position"] = "OH"
    s.save_roster(roster)

    gated_app.button(key="start_entering").click().run()
    assert s.role_of(MATCH["match_id"], 1, 7) == "OH"

    # Switching set copies the previous set's roles rather than starting blank.
    gated_app.button(key="goto_set::2").click().run()
    assert not gated_app.exception
    assert s.role_of(MATCH["match_id"], 2, 7) == "OH"


def test_events_are_stamped_with_the_role_of_that_set(gated_app):
    from volley import store as s

    gated_app.button(key="start_entering").click().run()
    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "S"},
    ])
    gated_app.run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert not gated_app.exception
    assert s.load_events().iloc[-1]["player_role"] == "S"


def test_changing_a_role_restamps_events_already_recorded(gated_app):
    from volley import store as s

    gated_app.button(key="start_entering").click().run()
    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "S"},
    ])
    gated_app.run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert s.load_events().iloc[-1]["player_role"] == "S"

    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OP"},
    ])
    s.restamp_roles(MATCH["match_id"], 1)
    assert s.load_events().iloc[-1]["player_role"] == "OP"


def test_the_same_player_in_two_roles_gets_two_rows(gated_app):
    """The point of all this: separate lines, not one blurred average."""
    from volley import stats
    from volley import store as s

    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"}])
    s.set_lineup(MATCH["match_id"], 2, [
        {"player_num": 7, "player_name": "Ana", "player_role": "MB"}])

    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    gated_app.button(key="goto_set::2").click().run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert not gated_app.exception

    per_match = stats.player_match_stats(s.load_events(), s.load_matches())
    ana = per_match[per_match["player_num"] == 7]
    assert sorted(ana["player_role"]) == ["MB", "OH"]

    season = stats.player_role_stats(s.load_events())
    ana_season = season[season["player_num"] == 7]
    assert sorted(ana_season["player_role"]) == ["MB", "OH"]
    assert list(ana_season["matches"]) == [1, 1]


# --- checking each set against the official record --------------------------

def comparison_table(app):
    for frame in app.dataframe:
        if "Profixio" in list(frame.value.columns):
            return frame.value
    return None


def record_set(app, set_no, us, them):
    """Enter one event and set the running score, as if that set had finished."""
    app.button(key=f"goto_set::{set_no}").click().run()
    app.session_state[f"score_us::{MATCH['match_id']}::{set_no}"] = us
    app.session_state[f"score_them::{MATCH['match_id']}::{set_no}"] = them
    app.run()
    record(app, 7, schema.ATTACK, "attempt")


def test_each_set_is_checked_separately(gated_app):
    gated_app.button(key="start_entering").click().run()
    record_set(gated_app, 1, 25, 9)
    assert not gated_app.exception

    table = comparison_table(gated_app)
    rows = {r["Set"]: (r["Profixio"], r["Entered"], r["Match"]) for r in table.to_dict("records")}
    assert rows["Set 1"] == ("25-9", "25-9", "✅")
    # The sets you have not done yet say so instead of looking wrong.
    assert rows["Set 2"][1] == "—"
    assert rows["Set 3"][1] == "—"


def test_a_wrong_set_score_is_flagged(gated_app):
    gated_app.button(key="start_entering").click().run()
    record_set(gated_app, 1, 25, 14)      # official says 25-9
    assert not gated_app.exception

    table = comparison_table(gated_app)
    rows = {r["Set"]: r["Match"] for r in table.to_dict("records")}
    assert rows["Set 1"] == "⚠️"
    assert any("wrong set number" in c.value for c in gated_app.caption)


def test_no_comparison_without_an_official_result(temp_store, monkeypatch):
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
    ]))
    store.upsert_match({**MATCH, "official_result": "", "official_sets": ""})

    app = past_setup(AppTest.from_file(APP, default_timeout=30)).run()
    record(app, 7, schema.ATTACK, "attempt")
    assert not app.exception
    assert comparison_table(app) is None


# --- moving between sets ----------------------------------------------------

def test_the_set_buttons_move_you_between_sets(gated_app):
    gated_app.button(key="start_entering").click().run()
    assert gated_app.session_state["set_no"] == 1

    gated_app.button(key="goto_set::3").click().run()
    assert not gated_app.exception
    assert gated_app.session_state["set_no"] == 3

    # Events then land in the set you moved to.
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert int(store.load_events().iloc[-1]["set_no"]) == 3


def test_next_set_advances_and_clears_the_selection(gated_app):
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key=f"action::{schema.ATTACK}").click().run()
    assert gated_app.session_state["sel_action"] is not None

    gated_app.button(key="next_set").click().run()
    assert not gated_app.exception
    assert gated_app.session_state["set_no"] == 2
    # A half-finished tap must not carry into the next set.
    assert gated_app.session_state["sel_action"] is None


def test_the_last_set_cannot_advance(gated_app):
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="goto_set::5").click().run()
    assert gated_app.button(key="next_set").disabled is True


def test_a_set_matching_the_official_score_is_marked_done(gated_app):
    gated_app.button(key="start_entering").click().run()
    gated_app.session_state[f"score_us::{MATCH['match_id']}::1"] = 25
    gated_app.session_state[f"score_them::{MATCH['match_id']}::1"] = 9
    gated_app.run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert not gated_app.exception

    assert gated_app.button(key="goto_set::1").label == "Set 1 ✅"
    assert gated_app.button(key="goto_set::2").label == "Set 2"
    assert any("ready for the next one" in c.value for c in gated_app.caption)


def test_the_lineup_carries_into_the_next_set(gated_app):
    from volley import store as s

    squad_table(gated_app, [(True, 7, "Ana", "OP")])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="next_set").click().run()
    record(gated_app, 7, schema.ATTACK, "attempt")

    last = s.load_events().iloc[-1]
    assert int(last["set_no"]) == 2
    assert last["player_role"] == "OP"


# --- opening the app cold ---------------------------------------------------

def test_the_app_opens_with_no_match_chosen(temp_store, monkeypatch):
    """The path a real first launch takes - no match_id in session state.

    Every other test presets one, which is how a missing default_match_id
    survived a green suite and broke the app on open.
    """
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
    ]))
    store.upsert_match({**MATCH, "official_result": "3-0",
                        "official_sets": "25-9, 25-5, 25-6"})

    app = offline(AppTest.from_file(APP, default_timeout=30)).run()
    assert not app.exception
    assert any("Match setup" in s.value for s in app.subheader)
    # It lands on the played match rather than the last fixture of the season.
    assert app.selectbox(key="setup_match").value == MATCH["match_id"]


def test_opening_cold_with_no_matches_at_all(temp_store, monkeypatch):
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)
    app = offline(AppTest.from_file(APP, default_timeout=30)).run()
    assert not app.exception
    assert any("No matches yet" in i.value for i in app.info)


def test_the_default_match_is_the_last_one_played(temp_store, monkeypatch):
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)
    for date_, opponent, result in (
        ("2026-09-26", "Jomala IK C", "3-0"),
        ("2026-10-03", "Jomala IK B", "3-0"),
        ("2026-11-15", "Taby Volley C", ""),
    ):
        store.upsert_match({
            "match_id": f"{date_}-{opponent.lower().replace(' ', '-')}",
            "date": date_, "opponent": opponent, "home_away": "home",
            "competition": "", "sets_won": 0, "sets_lost": 0, "video_url": "",
            "profixio_match_id": "", "squad": "", "official_result": result,
            "official_sets": "", "notes": "",
        })
    app = offline(AppTest.from_file(APP, default_timeout=30)).run()
    assert not app.exception
    assert app.selectbox(key="setup_match").value == "2026-10-03-jomala-ik-b"


# --- importing a protocol from the app --------------------------------------

@needs_protocol
def test_the_import_button_actually_imports(gated_app, monkeypatch):
    """Drives the app's own import, not profixio directly.

    Both the CLI and this went on passing a match id where protocol_to_events
    wants the whole match row, because every test called profixio directly and
    skipped the app's wrapper entirely.
    """
    from pathlib import Path as _Path

    from volley import profixio

    pdf = (_Path(__file__).parent / "fixtures" / "a_32681384.pdf").read_bytes()
    store.upsert_match({**MATCH, "profixio_match_id": "32681384"})
    monkeypatch.setattr(profixio, "find_downloaded_protocol",
                        lambda *a, **k: _Path("a_32681384.pdf"))
    monkeypatch.setattr(profixio, "read_protocol_file", lambda path: pdf)

    gated_app.run()
    gated_app.button(key="import_found").click().run()
    assert not gated_app.exception

    events = store.load_events()
    assert len(events) == 52
    assert set(events["source"]) == {schema.SOURCE_PROFIXIO}
    # The match details every row carries come from the match row, not an id.
    assert set(events["match_name"]) == {"Elden VBK vs Lions"}   # a home game
    assert set(events["match_date"]) == {MATCH["date"]}
    assert any("52 events" in s.value for s in gated_app.success)


# --- the workspace is a fragment, so it must not trust stale arguments ------

def test_linking_a_video_from_the_workspace_takes_effect(gated_app, monkeypatch):
    """A fragment keeps its arguments; saving inside it must still be seen."""
    from volley import video as video_module

    seen = []
    monkeypatch.setattr(video_module, "video_panel",
                        lambda video_id, **kwargs: seen.append(video_id))
    store.upsert_match({**MATCH, "video_url": ""})

    gated_app.button(key="start_entering").click().run()
    assert seen and seen[-1] is None          # no video on this match yet

    gated_app.text_input(key="video_url_input").set_value(
        "https://www.youtube.com/watch?v=pcRoX34oP7U&list=PLAelY3l5Ko3o&index=2"
    ).run()
    gated_app.button(key="save_video_url").click().run()
    assert not gated_app.exception

    assert seen[-1] == "pcRoX34oP7U", "the panel was handed a stale match row"
    stored = store.load_matches().iloc[0]["video_url"]
    assert "pcRoX34oP7U" in stored


def test_saving_roles_does_not_lose_the_video(gated_app, monkeypatch):
    from volley import store as s
    from volley import video as video_module

    seen = []
    monkeypatch.setattr(video_module, "video_panel",
                        lambda video_id, **kwargs: seen.append(video_id))
    s.upsert_match({**MATCH, "video_url": "https://youtu.be/pcRoX34oP7U"})

    gated_app.button(key="start_entering").click().run()
    assert seen[-1] == "pcRoX34oP7U"

    # Saving the set's roles must leave the video exactly where it was.
    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OP"},
    ])
    gated_app.run()
    assert not gated_app.exception
    assert seen[-1] == "pcRoX34oP7U"


def test_an_edit_is_folded_into_the_row_it_came_from():
    """Streamlit reports only what changed, positioned by row index."""
    import app as application

    rows = [
        {"player_num": 4, "player_name": "Cyd", "player_role": "MB"},
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"},
    ]
    merged = application.apply_edits(rows, {1: {"player_role": "OP"}})
    assert merged[1]["player_role"] == "OP"
    assert merged[0]["player_role"] == "MB"       # untouched
    assert rows[1]["player_role"] == "OH"         # and the original is not mutated


def test_edits_outside_the_table_are_ignored():
    import app as application

    rows = [{"player_num": 7, "player_name": "Ana", "player_role": "OH"}]
    assert application.apply_edits(rows, {9: {"player_role": "S"}}) == rows
    assert application.apply_edits(rows, {0: {"nonsense": "x"}}) == rows
    assert application.apply_edits(rows, {}) == rows
    assert application.apply_edits(rows, None) == rows


def test_a_role_change_lands_on_the_set_you_are_looking_at(gated_app):
    """Changing set 2 must not write to set 1, which is what it felt like."""
    from volley import store as s

    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="goto_set::2").click().run()
    assert gated_app.session_state["set_no"] == 2

    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"}])
    s.set_lineup(MATCH["match_id"], 2, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"}])

    import app as application
    rows = [{"player_num": 7, "player_name": "Ana", "player_role": "OH"}]
    s.set_lineup(MATCH["match_id"], 2,
                 application.apply_edits(rows, {0: {"player_role": "S"}}))
    gated_app.run()

    assert not gated_app.exception
    assert gated_app.session_state["set_no"] == 2        # still where you were
    assert s.role_of(MATCH["match_id"], 2, 7) == "S"
    assert s.role_of(MATCH["match_id"], 1, 7) == "OH"    # set 1 untouched


def test_there_is_no_save_roles_button_any_more(gated_app):
    gated_app.button(key="start_entering").click().run()
    assert not [b.key for b in gated_app.button if b.key.endswith("::save")]
    assert any("save as you make them" in c.value for c in gated_app.caption)


# --- review duplicates ------------------------------------------------------

@needs_protocol
def test_only_point_scoring_events_are_ever_reviewed(gated_app):
    """A reception cannot collide with a protocol, so it is never at risk."""
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    for action, result in ((schema.RECEPTION, "perfect"), (schema.DIG, "dig"),
                           (schema.ATTACK, "attempt"), (schema.ATTACK, "kill")):
        record(gated_app, 7, action, result)

    candidates = store.duplicate_candidates(MATCH["match_id"], 1)
    kinds = {(r["action"], r["action_result"]) for r in candidates.to_dict("records")}
    assert (schema.RECEPTION, "perfect") not in kinds
    assert (schema.DIG, "dig") not in kinds
    assert (schema.ATTACK, "attempt") not in kinds
    assert (schema.ATTACK, "kill") in kinds


@needs_protocol
def test_a_duplicate_is_unticked_and_a_correction_is_kept(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    # #7 has protocol serve aces; #12 has nothing at all.
    record(gated_app, 7, schema.SERVE, "ace")
    record(gated_app, 12, schema.SERVE, "ace")

    rows = store.duplicate_candidates(MATCH["match_id"], 1)
    mine = rows[rows["source"] == schema.SOURCE_MANUAL]
    duplicate = mine[mine["player_num"] == 7].iloc[0]
    correction = mine[mine["player_num"] == 12].iloc[0]
    assert bool(duplicate["keep"]) is False      # the protocol already has these
    assert bool(correction["keep"]) is True      # nothing official to clash with
    assert all(rows[rows["source"] == schema.SOURCE_PROFIXIO]["keep"])


@needs_protocol
def test_applying_removes_only_the_unticked_rows(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.SERVE, "ace")        # a duplicate
    record(gated_app, 7, schema.RECEPTION, "perfect")  # never at risk
    before = len(store.load_events())

    gated_app.button(key="reopen_setup").click().run()
    apply_key = f"dupes_apply::{MATCH['match_id']}::1"
    gated_app.button(key=apply_key).click().run()
    assert not gated_app.exception

    after = store.load_events()
    assert len(after) == before - 1
    # The reception is still there; the duplicated ace is gone.
    assert len(after[after["action"] == schema.RECEPTION]) == 1
    manual_aces = after[(after["source"] == schema.SOURCE_MANUAL)
                        & (after["action"] == schema.SERVE)]
    assert len(manual_aces) == 0


@needs_protocol
def test_nothing_happens_until_apply(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.SERVE, "ace")
    before = len(store.load_events())

    gated_app.button(key="reopen_setup").click().run()
    assert len(store.load_events()) == before     # rendering the panel changes nothing


# --- the set must not move underneath you -----------------------------------

def test_the_set_survives_every_kind_of_tap(gated_app):
    """It was a sidebar radio, outside the fragment, and snapped back to 1.

    Recording against the wrong set is close to invisible while it happens, so
    this walks the whole entry loop and checks the set after every step.
    """
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="goto_set::2").click().run()
    assert gated_app.session_state["set_no"] == 2

    gated_app.button(key=f"action::{schema.ATTACK}").click().run()
    assert gated_app.session_state["set_no"] == 2
    gated_app.button(key=f"result::{schema.ATTACK}::attempt").click().run()
    assert gated_app.session_state["set_no"] == 2
    gated_app.button(key="player::p7").click().run()
    assert gated_app.session_state["set_no"] == 2

    # ...and the event landed on set 2, which is the thing that matters.
    assert int(store.load_events().iloc[-1]["set_no"]) == 2

    # A full rerun must not undo it either.
    gated_app.run()
    assert gated_app.session_state["set_no"] == 2
    record(gated_app, 7, schema.DIG, "dig")
    assert int(store.load_events().iloc[-1]["set_no"]) == 2


def test_the_set_is_only_changed_by_the_set_strip(gated_app):
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="goto_set::3").click().run()

    # Undo, score buttons and the roles table all leave it alone.
    record(gated_app, 7, schema.ATTACK, "attempt")
    event_id = store.load_events().iloc[-1]["event_id"]
    gated_app.button(key=f"undo::{event_id}").click().run()
    assert gated_app.session_state["set_no"] == 3

    gated_app.button(key=f"bump::score_them::{MATCH['match_id']}::3").click().run()
    assert gated_app.session_state["set_no"] == 3
    assert not gated_app.exception


def test_there_is_only_one_set_control(gated_app):
    """Two of them is how the sidebar one went stale without being noticed."""
    gated_app.button(key="start_entering").click().run()
    assert not [r for r in gated_app.radio if r.key == "set_no"]
    assert len([b for b in gated_app.button if b.key.startswith("goto_set::")]) == 5


# --- the line-up owns the name, not the roster ------------------------------

def editor_rows(app, match_id=None):
    """Stand in for the event data editor, which AppTest cannot click."""
    match_id = match_id or MATCH["match_id"]
    return store.match_events(store.load_events(), match_id)[schema.EVENT_COLUMNS].copy()


def save_editor(app, frame, match_id=None):
    """Seed the editor's stash and press Save.

    Run first so the button exists for events seeded since the last render,
    then overwrite the stash: the callback reads it before the next rerun.
    """
    match_id = match_id or MATCH["match_id"]
    app.run()
    app.session_state[f"editor_edit::{match_id}"] = frame
    app.button(key="save_edits").click().run()
    return app


def test_saving_edits_keeps_the_lineup_name_not_the_rosters(app):
    """#4 was one player that day; the roster has since given #4 to another.

    Saving used to look the name up in the roster by number, so every point
    the first player scored came back stamped with the current holder of her
    old shirt - including rows the official protocol had named correctly.
    """
    match_id = MATCH["match_id"]
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 4, "name": "Elin", "position": "S", "active": True},
        {"player_id": "", "number": 17, "name": "Nadia", "position": "S", "active": True},
    ]))
    store.set_lineup(match_id, 1, [
        {"player_num": 4, "player_name": "Nadia", "player_role": "S"}])
    store.append_event(store.build_event(
        match=MATCH, set_no=1, seq=1,
        player={"number": 4, "name": "Nadia"},
        action=schema.SERVE, result="ace",
    ))

    save_editor(app, editor_rows(app))
    assert not app.exception
    assert list(store.load_events()["player_name"]) == ["Nadia"]


def test_changing_the_number_re_resolves_the_name_from_the_lineup(app):
    match_id = MATCH["match_id"]
    store.set_lineup(match_id, 1, [
        {"player_num": 4, "player_name": "Nadia", "player_role": "S"},
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"},
    ])
    store.append_event(store.build_event(
        match=MATCH, set_no=1, seq=1,
        player={"number": 4, "name": "Nadia"},
        action=schema.ATTACK, result="kill",
    ))

    frame = editor_rows(app)
    frame.loc[frame.index[0], "player_num"] = 7     # it was Ana's kill
    save_editor(app, frame)

    assert not app.exception
    saved = store.load_events().iloc[0]
    assert saved["player_num"] == 7
    assert saved["player_name"] == "Ana"


def test_a_number_the_lineup_does_not_know_keeps_its_name(app):
    """Better a name that is merely old than one that is confidently wrong."""
    store.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"}])
    store.append_event(store.build_event(
        match=MATCH, set_no=1, seq=1,
        player={"number": 23, "name": "Guest"},
        action=schema.DIG, result="dig",
    ))

    save_editor(app, editor_rows(app))
    assert store.load_events().iloc[0]["player_name"] == "Guest"


def test_saving_leaves_untouched_rows_alone(app):
    """Saving used to rewrite the whole match and mark all of it unpushed."""
    store.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"}])
    for seq, result in enumerate(["ace", "in"], start=1):
        store.append_event(store.build_event(
            match=MATCH, set_no=1, seq=seq,
            player={"number": 7, "name": "Ana"},
            action=schema.SERVE, result=result,
        ))
    store.mark_synced(store.load_events()["event_id"])

    frame = editor_rows(app)
    frame.loc[frame.index[0], "action_result"] = "error"
    save_editor(app, frame)

    saved = store.load_events().set_index("event_id")
    changed = saved[saved["action_result"] == "error"].iloc[0]
    untouched = saved[saved["action_result"] == "in"].iloc[0]
    assert bool(changed["synced"]) is False       # needs re-pushing
    assert bool(untouched["synced"]) is True      # was never edited


def test_editing_what_a_row_claims_withdraws_its_review(app):
    store.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OH"}])
    store.append_event(store.build_event(
        match=MATCH, set_no=1, seq=1,
        player={"number": 7, "name": "Ana"},
        action=schema.SERVE, result="ace",
    ))
    store.mark_reviewed(store.load_events()["event_id"])

    frame = editor_rows(app)
    frame.loc[frame.index[0], "action_result"] = "in"
    save_editor(app, frame)

    assert bool(store.load_events().iloc[0]["reviewed"]) is False


# --- an assist is a set that ended in a kill --------------------------------

def test_an_assist_records_the_hitters_kill_too(app):
    record(app, 12, schema.SET, "assist", target=7)
    assert not app.exception

    events = store.load_events()
    assert len(events) == 2

    assist = events[events["action"] == schema.SET].iloc[0]
    kill = events[events["action"] == schema.ATTACK].iloc[0]
    assert assist["player_num"] == 12 and assist["action_result"] == "assist"
    assert int(assist["target_num"]) == 7
    assert kill["player_num"] == 7 and kill["action_result"] == "kill"
    assert bool(kill["is_point"]) is True
    assert bool(assist["is_point"]) is False
    # The second event must not reuse the first one's number.
    assert assist["seq"] != kill["seq"]


def test_the_assists_kill_moves_the_score_once(app):
    """One point for the rally, not two, and none for the assist."""
    record(app, 12, schema.SET, "assist", target=7)
    us, them = store.current_score(store.load_events(), MATCH["match_id"], 1)
    assert (us, them) == (1, 0)


def test_a_plain_kill_still_writes_one_event(app):
    record(app, 7, schema.ATTACK, "kill")
    assert len(store.load_events()) == 1


# --- review duplicates remembers what you decided ---------------------------

@needs_protocol
def test_a_kept_row_stays_kept_on_the_next_look(gated_app):
    """The trap: corrections you deliberately kept came back for deletion."""
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.SERVE, "ace")        # the protocol has these
    gated_app.button(key="reopen_setup").click().run()

    mine = store.duplicate_candidates(MATCH["match_id"], 1)
    mine = mine[mine["source"] == schema.SOURCE_MANUAL]
    assert bool(mine.iloc[0]["keep"]) is False       # unticked, as a guess

    # Say "no, that one is real" and apply.
    stash = gated_app.session_state[f"dupes_edit::{MATCH['match_id']}::1"].copy()
    stash["keep"] = True
    gated_app.session_state[f"dupes_edit::{MATCH['match_id']}::1"] = stash
    gated_app.button(key=f"dupes_apply::{MATCH['match_id']}::1").click().run()
    assert not gated_app.exception

    again = store.duplicate_candidates(MATCH["match_id"], 1)
    again = again[again["source"] == schema.SOURCE_MANUAL]
    assert len(again) == 1                           # still there
    assert bool(again.iloc[0]["keep"]) is True       # and still ticked
    assert bool(again.iloc[0]["reviewed"]) is True


@needs_protocol
def test_applying_marks_what_it_kept_as_reviewed(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 12, schema.SERVE, "ace")       # a correction, kept
    gated_app.button(key="reopen_setup").click().run()
    gated_app.button(key=f"dupes_apply::{MATCH['match_id']}::1").click().run()

    events = store.load_events()
    kept = events[(events["source"] == schema.SOURCE_MANUAL)
                  & (events["action"] == schema.SERVE)]
    assert len(kept) == 1
    assert bool(kept.iloc[0]["reviewed"]) is True
    # The protocol's own rows are settled too.
    protocol = events[events["source"] == schema.SOURCE_PROFIXIO]
    assert bool(protocol[protocol["set_no"] == 1]["reviewed"].all())


@needs_protocol
def test_a_new_event_after_a_review_is_unreviewed(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.SERVE, "ace")
    gated_app.button(key="reopen_setup").click().run()
    stash = gated_app.session_state[f"dupes_edit::{MATCH['match_id']}::1"].copy()
    stash["keep"] = True                             # keep it, deliberately
    gated_app.session_state[f"dupes_edit::{MATCH['match_id']}::1"] = stash
    gated_app.button(key=f"dupes_apply::{MATCH['match_id']}::1").click().run()

    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.SERVE, "ace")        # one more, later

    mine = store.duplicate_candidates(MATCH["match_id"], 1)
    mine = mine[mine["source"] == schema.SOURCE_MANUAL]
    # The settled one stays settled; only the new one is asked about.
    assert sorted(bool(v) for v in mine["reviewed"]) == [False, True]
    assert sorted(bool(v) for v in mine["keep"]) == [False, True]
