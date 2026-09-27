"""End-to-end: run the real Streamlit script and drive it like a user would.

Streamlit reruns the whole script on every interaction, so a smoke test that
actually clicks is the only way to catch session-state and callback mistakes.
"""

import base64

import pandas as pd
import pytest

from volley import schema, store, video

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

VIDEO_URL = "https://youtu.be/dQw4w9WgXcQ"

def offline(app):
    """Stop the app auto-connecting to Google during a test."""
    app.session_state["connect_attempted"] = True
    return app


def record(app, number, action, result):
    """Record one event the only way there is now: three taps."""
    app.button(key=f"player::p{number}").click().run()
    app.button(key=f"action::{action}").click().run()
    app.button(key=f"result::{action}::{result}").click().run()
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
    return past_setup(AppTest.from_file("app.py", default_timeout=30)).run()


def test_app_renders_without_exceptions(app):
    assert not app.exception
    assert any("Volleyball Stats" in title.value for title in app.title)


def test_three_clicks_record_an_event_and_bump_the_score(app):
    app.button(key="player::p7").click().run()
    assert not app.exception
    app.button(key=f"action::{schema.ATTACK}").click().run()
    assert not app.exception
    app.button(key=f"result::{schema.ATTACK}::kill").click().run()
    assert not app.exception

    events = store.load_events()
    assert len(events) == 1
    row = events.iloc[0]
    assert (row["player_num"], row["action"], row["action_result"]) == (7, schema.ATTACK, "kill")
    assert row["score_us"] == 1          # a kill is a point
    assert row["score_them"] == 0
    assert row["synced"] == False        # noqa: E712 - nothing pushed yet

    # Selection resets so the next event starts from the player grid again.
    assert app.session_state["sel_player"] is None
    assert app.session_state["sel_action"] is None


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

    restarted = past_setup(AppTest.from_file("app.py", default_timeout=30))
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
    return past_setup(AppTest.from_file("app.py", default_timeout=30)), box


def test_events_are_still_recorded_with_no_video_linked(temp_store, monkeypatch):
    """The video is an aid, not a dependency - entry must work without it."""
    store.save_roster(pd.DataFrame([
        {"player_id": "", "number": 7, "name": "Ana", "position": "OH", "active": True},
    ]))
    store.upsert_match({**MATCH, "video_url": ""})
    monkeypatch.setattr(video, "video_panel", lambda *args, **kwargs: None)

    app = past_setup(AppTest.from_file("app.py", default_timeout=30)).run()
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
    app = offline(AppTest.from_file("app.py", default_timeout=30)).run()
    assert not app.exception
    assert any("Elden VBK" in title.value for title in app.title)


def test_renders_the_logo_when_the_file_is_there(blank_app):
    tmp_path, monkeypatch = blank_app
    logo = tmp_path / "elden-vbk.png"
    logo.write_bytes(TINY_PNG)
    monkeypatch.setenv("VOLLEY_LOGO", str(logo))
    app = offline(AppTest.from_file("app.py", default_timeout=30)).run()
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
    app = offline(AppTest.from_file("app.py", default_timeout=30))
    app.session_state["match_id"] = MATCH["match_id"]
    return app.run()


def test_setup_blocks_the_workspace_until_confirmed(gated_app):
    assert not gated_app.exception
    assert any("Match setup" in s.value for s in gated_app.subheader)
    # The entry surface is not reachable yet.
    with pytest.raises(KeyError):
        gated_app.button(key="player::p7")


def test_starting_entry_opens_the_workspace_and_saves_the_squad(gated_app):
    gated_app.checkbox(key=f"squad::{MATCH['match_id']}::12").set_value(False).run()
    gated_app.button(key="start_entering").click().run()
    assert not gated_app.exception

    assert gated_app.session_state["setup_done_for"] == MATCH["match_id"]
    assert gated_app.button(key="player::p7") is not None
    match = store.load_matches().iloc[0].to_dict()
    assert store.squad_numbers(match) == [4, 7]


def test_the_squad_filters_the_player_grid(gated_app):
    gated_app.checkbox(key=f"squad::{MATCH['match_id']}::12").set_value(False).run()
    gated_app.button(key="start_entering").click().run()

    keys = [b.key for b in gated_app.button if b.key.startswith("player::")]
    assert keys == ["player::p4", "player::p7"]


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


# --- protocol and video must not double count -------------------------------

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


def test_scoring_actions_are_locked_once_the_protocol_is_in(gated_app):
    """Every point is already imported - recording a kill again would double it."""
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="player::p7").click().run()
    gated_app.button(key=f"action::{schema.ATTACK}").click().run()

    kill = gated_app.button(key=f"result::{schema.ATTACK}::kill")
    attempt = gated_app.button(key=f"result::{schema.ATTACK}::attempt")
    assert kill.disabled is True
    assert attempt.disabled is False


def test_non_scoring_actions_stay_available(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="player::p7").click().run()
    gated_app.button(key=f"action::{schema.RECEPTION}").click().run()

    for result in schema.ACTIONS[schema.RECEPTION]:
        assert gated_app.button(key=f"result::{schema.RECEPTION}::{result}").disabled is False


def test_the_override_reopens_scoring(gated_app):
    import_jomala_protocol(MATCH["match_id"])
    gated_app.button(key="start_entering").click().run()
    gated_app.toggle(key="allow_scoring").set_value(True).run()

    before = len(store.load_events())
    record(gated_app, 7, schema.ATTACK, "kill")
    assert not gated_app.exception
    assert len(store.load_events()) == before + 1


def test_nothing_is_locked_without_a_protocol(gated_app):
    """A match with no protocol imported behaves exactly as before."""
    gated_app.button(key="start_entering").click().run()
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
    gated_app.radio(key="set_no").set_value(2).run()
    assert not gated_app.exception
    assert s.role_of(MATCH["match_id"], 2, 7) == "OH"


def test_events_are_stamped_with_the_role_of_that_set(gated_app):
    from volley import store as s

    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "S"},
    ])
    gated_app.button(key="start_entering").click().run()
    record(gated_app, 7, schema.ATTACK, "attempt")
    assert not gated_app.exception
    assert s.load_events().iloc[-1]["player_role"] == "S"


def test_changing_a_role_restamps_events_already_recorded(gated_app):
    from volley import store as s

    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "S"},
    ])
    gated_app.button(key="start_entering").click().run()
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
    gated_app.radio(key="set_no").set_value(2).run()
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
    app.radio(key="set_no").set_value(set_no).run()
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

    app = past_setup(AppTest.from_file("app.py", default_timeout=30)).run()
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
    gated_app.button(key="player::p7").click().run()
    assert gated_app.session_state["sel_player"] is not None

    gated_app.button(key="next_set").click().run()
    assert not gated_app.exception
    assert gated_app.session_state["set_no"] == 2
    # A half-finished tap must not carry into the next set.
    assert gated_app.session_state["sel_player"] is None


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

    s.set_lineup(MATCH["match_id"], 1, [
        {"player_num": 7, "player_name": "Ana", "player_role": "OP"},
    ])
    gated_app.button(key="start_entering").click().run()
    gated_app.button(key="next_set").click().run()
    record(gated_app, 7, schema.ATTACK, "attempt")

    last = s.load_events().iloc[-1]
    assert int(last["set_no"]) == 2
    assert last["player_role"] == "OP"
