"""Elden VBK volleyball box-score entry.

Run with:  streamlit run app.py
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from volley import config, profixio, schema, sheets, stats, store, video

LOGO = config.logo_path()

st.set_page_config(page_title=f"{config.club_name()} · Stats", page_icon="🏐", layout="wide")

# Streamlit spaces every block a full row apart, which pushes the buttons well
# below the video. Only the entry strip is tightened; the rest keeps its air.
TIGHTEN_ENTRY = """
<style>
  .st-key-entry_strip { margin-top: -1.4rem; }
  .st-key-entry_strip [data-testid="stCaptionContainer"] { margin-bottom: -0.4rem; }
</style>
"""

BOX_SCORE_VIEW = [
    "player_num", "player_name", "player_role", "points", "kills", "attack_errors",
    "attempts", "kill_pct", "hitting_eff", "aces", "serve_errors", "reception_count",
    "pass_rating", "blocks", "digs", "assists",
]


# --- small state helpers ----------------------------------------------------

def init_state() -> None:
    defaults = {
        "match_id": "",
        "set_no": 1,
        "sel_action": None,
        "sel_result": None,
        "sel_player": None,
        "flash": None,
        "spreadsheet": None,
        "spreadsheet_title": "",
        "mapping": {},
        "tab_titles": [],
        "show_video": True,
        "video_layout": "On top",
        "video_height": 420,
        "video_width": 4,
        "setup_done_for": "",
        "connect_attempted": False,
        "auth_command": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    # Rows written before events carried a registration stamp need one, or they
    # would all sort together at the bottom. Runs once per session and does
    # nothing at all once every row is stamped.
    if not st.session_state.get("backfilled"):
        store.backfill_recorded_at()
        st.session_state["backfilled"] = True


def flash(kind: str, message: str) -> None:
    st.session_state.flash = (kind, message)


def score_keys(match_id: str, set_no: int) -> tuple[str, str]:
    return f"score_us::{match_id}::{set_no}", f"score_them::{match_id}::{set_no}"


def ensure_score_state(events: pd.DataFrame, match_id: str, set_no: int) -> None:
    """Seed the score widgets, preferring the official record.

    A set with a protocol already has a score for every point, so take it. The
    running total only has to be maintained by hand when there is nothing
    official to take it from.
    """
    us_key, them_key = score_keys(match_id, set_no)
    if us_key in st.session_state and them_key in st.session_state:
        return
    official = store.protocol_score(match_id, set_no)
    us, them = official if official else store.current_score(events, match_id, set_no)
    st.session_state.setdefault(us_key, us)
    st.session_state.setdefault(them_key, them)


def current_video_id() -> str | None:
    return video.parse_youtube_id(st.session_state.get("video_url_current", ""))


# --- recording --------------------------------------------------------------

def record(match: dict, player: dict, action: str, result: str, target_num=None) -> dict:
    """Move the score, write one event, and hand back the row that was written.

    Separate from `commit` because an assist records two events and they have
    to share one selection reset and one message. Each call re-reads the buffer
    so a second event gets the next `seq` rather than colliding with the first.
    """
    match_id = match["match_id"]
    set_no = int(st.session_state.set_no)
    us_key, them_key = score_keys(match_id, set_no)

    # With an official protocol the score is already known for every point, so
    # recording an action never moves it - that is what stops a correction from
    # also inflating the set. Without one, keep count as you go.
    if store.protocol_score(match_id, set_no) is None:
        if schema.is_point(action, result):
            st.session_state[us_key] = int(st.session_state[us_key]) + 1
        elif result == "error":
            st.session_state[them_key] = int(st.session_state[them_key]) + 1

    events = store.load_events()
    event = store.build_event(
        match=match,
        set_no=set_no,
        seq=store.next_seq(events, match_id, set_no),
        player=player,
        action=action,
        result=result,
        score_us=int(st.session_state[us_key]),
        score_them=int(st.session_state[them_key]),
        role=store.role_of(match_id, set_no, player["number"], player.get("position", "")),
        target_num=target_num,
    )
    store.append_event(event)
    return event


def describe(event: dict) -> str:
    to = f" → #{event['target_num']}" if event["target_num"] not in ("", None) else ""
    return (f"#{event['player_num']} {event['player_name']} · "
            f"{event['action'].lower()} {event['action_result']}{to}")


def clear_selection() -> None:
    st.session_state.sel_action = None
    st.session_state.sel_result = None
    st.session_state.sel_player = None


def commit(match: dict, player: dict, action: str, result: str, target_num=None) -> None:
    event = record(match, player, action, result, target_num)
    clear_selection()
    flash("success", describe(event))


# --- callbacks (run before the script reruns) ------------------------------

def cb_pick_action(action: str) -> None:
    st.session_state.sel_action = action
    st.session_state.sel_result = None
    st.session_state.sel_player = None


def cb_pick_result(result: str) -> None:
    st.session_state.sel_result = result
    st.session_state.sel_player = None


def cb_pick_player(match: dict, player: dict) -> None:
    """The player tap commits - unless it is an assist, which needs a target."""
    action = st.session_state.sel_action
    result = st.session_state.sel_result
    if not action or not result:
        return
    if action == schema.SET and result == "assist":
        st.session_state.sel_player = player
        return
    commit(match, player, action, result)


def cb_pick_target(match: dict, target: dict) -> None:
    """The setter's assist and the hitter's kill, from the one tap.

    An assist is by definition a set that ended in a kill, so the kill is
    recorded too rather than asked for a second time. The protocol may already
    hold that kill; recording it anyway is deliberate, because the point of
    entering by hand is to complete what Profixio missed. A genuine double is
    settled once in Review duplicates, which now remembers what you decided.
    """
    setter = st.session_state.sel_player
    if not setter:
        return
    assist = record(match, setter, schema.SET, "assist",
                    target_num=int(target["number"]))
    kill = record(match, target, schema.ATTACK, "kill")
    clear_selection()
    flash("success", f"{describe(assist)}  ·  {describe(kill)}")


def cb_clear_selection() -> None:
    clear_selection()


def cb_goto_set(set_no: int) -> None:
    st.session_state.set_no = int(set_no)
    st.session_state.sel_action = None
    st.session_state.sel_result = None
    st.session_state.sel_player = None


def cb_bump(key: str, delta: int) -> None:
    st.session_state[key] = max(0, int(st.session_state[key]) + delta)


def cb_undo(event_id: str) -> None:
    store.delete_event(event_id)
    flash("success", "Event removed")


def cb_new_match() -> None:
    """Create a match that is not in Profixio - a friendly, say."""
    opponent = st.session_state.get("new_opponent", "").strip()
    if not opponent:
        flash("error", "Opponent is required")
        return
    match_date = st.session_state.get("new_date", date.today()).isoformat()
    match_id = store.new_match_id(match_date, opponent)
    store.upsert_match({
        "match_id": match_id,
        "date": match_date,
        "opponent": opponent,
        "home_away": st.session_state.get("new_home_away", "home"),
        "competition": "",
        "sets_won": 0,
        "sets_lost": 0,
        "video_url": "",
        "profixio_match_id": "",
        "squad": "",
        "official_result": "",
        "official_sets": "",
        "notes": "",
    })
    st.session_state.match_id = match_id
    st.session_state.set_no = 1
    flash("success", f"Match created: {match_id}")


def cb_reopen_setup() -> None:
    st.session_state.setup_done_for = ""


def cb_start_entering(match_id: str) -> None:
    """Save the one squad table and open the workspace."""
    save_squad(match_id)
    st.session_state.setup_done_for = match_id


def apply_edits(rows: list, edits: dict) -> list:
    """Fold a data editor's edits back into the rows it was built from.

    Streamlit reports them as {"edited_rows": {row index: {column: value}}} -
    only what changed, positioned by row. Kept separate from the callback so it
    can be tested without a script run.
    """
    merged = [dict(row) for row in rows]
    for index, changed in (edits or {}).items():
        index = int(index)
        if 0 <= index < len(merged):
            merged[index].update(
                {key: value for key, value in changed.items() if key in merged[index]}
            )
    return merged


def cb_roles_changed(match_id: str, set_no: int, rows: list, key: str) -> None:
    """Save a role the moment it is picked.

    A separate Save button was a step too many - you change the dropdown and
    expect it to be changed.
    """
    edits = (st.session_state.get(key) or {}).get("edited_rows", {})
    if not edits:
        return
    store.set_lineup(match_id, set_no, [
        {
            "player_num": int(row["player_num"]),
            "player_name": row["player_name"],
            "player_role": str(row["player_role"] or ""),
        }
        for row in apply_edits(rows, edits)
    ])
    # Events already recorded carry the name and role as they were when you
    # tapped; push the correction through so the two cannot quietly disagree.
    store.restamp_players(match_id, set_no)
    store.restamp_roles(match_id, set_no)


def cb_save_video_url(match: dict) -> None:
    url = st.session_state.get("video_url_input", "").strip()
    if url and not video.parse_youtube_id(url):
        flash("error", "That does not look like a YouTube URL")
        return
    store.upsert_match({**match, "video_url": url})
    flash("success", "Video linked to this match" if url else "Video unlinked")


# --- sidebar ----------------------------------------------------------------

def sidebar_branding() -> None:
    if LOGO.exists():
        st.logo(str(LOGO), size="large")
        st.sidebar.image(str(LOGO), width=120)
    else:
        st.sidebar.markdown("### ELDEN VBK")
        st.sidebar.caption("Add assets/elden-vbk.png for the club logo.")


def connect(spreadsheet_id: str, announce: bool = True) -> bool:
    """Open the spreadsheet and work out the tab mapping. Never raises."""
    try:
        client = sheets.get_client()
        spreadsheet = sheets.open_spreadsheet(client, spreadsheet_id)
        st.session_state.spreadsheet = spreadsheet
        st.session_state.spreadsheet_title = spreadsheet.title
        st.session_state.mapping = sheets.resolve_mapping(
            spreadsheet, store.load_sheet_config()
        )
        st.session_state.tab_titles = sheets.list_tab_titles(spreadsheet)
        if announce:
            flash("success", f"Connected to {spreadsheet.title}")
        return True
    except sheets.SheetsError as exc:
        st.session_state.spreadsheet = None
        st.session_state.auth_command = getattr(exc, "command", "")
        flash("error", str(exc))
    except Exception as exc:
        st.session_state.spreadsheet = None
        st.session_state.auth_command = ""
        flash("error", f"Could not connect: {exc}")
    return False


def sidebar_connection() -> None:
    st.sidebar.subheader("Google Sheets")
    spreadsheet_id = st.sidebar.text_input(
        "Spreadsheet ID",
        value=config.spreadsheet_id(),
        key="spreadsheet_id",
        help="Saved in .env - you should not need to touch this.",
    )

    # Connect by itself on first load, so the normal case needs no clicking.
    if not st.session_state.connect_attempted and spreadsheet_id.strip():
        st.session_state.connect_attempted = True
        connect(spreadsheet_id, announce=False)

    if st.session_state.spreadsheet is not None:
        st.sidebar.success(f"Connected · {st.session_state.spreadsheet_title}")
    else:
        st.sidebar.warning("Not connected")
    if st.sidebar.button("Connect", key="connect", width="stretch"):
        if not spreadsheet_id.strip():
            flash("error", "Paste a spreadsheet ID first")
        else:
            connect(spreadsheet_id)

    if st.session_state.spreadsheet is None:
        return

    with st.sidebar.expander("Tab mapping"):
        st.caption(
            "Which existing tab holds each kind of data. Rows are appended and "
            "unknown columns are left alone \u2014 nothing here is ever rewritten."
        )
        titles = st.session_state.tab_titles
        chosen = dict(st.session_state.mapping)
        # Only the tabs a push actually writes can be mapped; the rest would be
        # a choice with no effect.
        writable = {
            role: title for role, title in schema.MAPPABLE_ROLES.items()
            if title in config.push_tabs()
        }
        for role, default_title in writable.items():
            options = list(titles)
            new_option = f"\u2795 create \u201c{default_title}\u201d"
            if default_title not in options:
                options.append(new_option)
            current = st.session_state.mapping.get(role, default_title)
            if current not in options:
                options.append(current)
            chosen[role] = st.selectbox(
                role.title(), options, index=options.index(current), key=f"map::{role}"
            )
            if chosen[role] == new_option:
                chosen[role] = default_title
        if st.button("Save mapping", key="save_mapping", width="stretch"):
            st.session_state.mapping = chosen
            store.save_sheet_config(chosen)
            flash("success", "Tab mapping saved")
        st.caption(
            "A push writes " + ", ".join(f"`{t}`" for t in config.push_tabs())
            + " — set `VOLLEY_PUSH_TABS` in .env to change that. Tabs rebuilt from "
            "scratch each push are not mappable."
        )


def sidebar_push(events: pd.DataFrame) -> None:
    pending = len(store.unsynced(events))
    label = f"Push to Sheets ({pending} new)" if pending else "Push to Sheets"
    disabled = st.session_state.spreadsheet is None
    if st.sidebar.button(label, key="push", type="primary", width="stretch", disabled=disabled):
        try:
            result = sheets.push(
                st.session_state.spreadsheet,
                events.drop(columns=schema.LOCAL_ONLY_COLUMNS, errors="ignore"),
                store.load_matches(),
                st.session_state.mapping,
                store.load_lineup(),
            )
            store.mark_synced(events["event_id"])
            written = ", ".join(f"{title} ({rows})" for title, rows in result["tabs"].items())
            flash("success",
                  f"Published {written} from {result['events_total']} events.")
        except sheets.SheetsError as exc:
            flash("error", str(exc))
        except Exception as exc:
            flash("error", f"Push failed: {exc}")
    if disabled:
        st.sidebar.caption("Connect a spreadsheet to enable pushing.")
        return

    archives_events = schema.TAB_EVENTS in config.push_tabs()
    if st.sidebar.button("⬇ Restore from Sheets", key="restore", width="stretch",
                         disabled=not archives_events,
                         help="Pull archived events back into this machine"):
        try:
            title = st.session_state.mapping.get("events", schema.TAB_EVENTS)
            result = store.restore_events(
                sheets.read_events(st.session_state.spreadsheet, title)
            )
            flash("success",
                  f"Restored {result['added']} event(s); "
                  f"{result['already_here']} were already here.")
        except Exception as exc:
            flash("error", f"Could not restore: {exc}")
    if not archives_events:
        st.sidebar.caption(
            "Only `PlayerSetStats` is published, and an aggregate cannot be turned back "
            "into events. Add `Events` to `VOLLEY_PUSH_TABS` in .env to make this machine "
            "recoverable."
        )


def sidebar_match(matches: pd.DataFrame) -> None:
    st.sidebar.subheader("Match")
    match_id = st.session_state.match_id
    row = matches[matches["match_id"] == match_id]
    if len(row):
        match = row.iloc[0]
        st.sidebar.markdown(
            f"**{match['opponent']}**  \n{match['date']} \u00b7 {match['home_away']}"
        )
    else:
        st.sidebar.caption("No match selected.")
    if st.sidebar.button("\u2699 Match setup", key="reopen_setup", width="stretch"):
        st.session_state.setup_done_for = ""
        st.rerun()

    # No set control here. It used to be a sidebar radio, and because the
    # workspace is a fragment the sidebar is not re-rendered when you tap
    # inside it - so the radio went stale and snapped back to set 1 on the next
    # full rerun, quietly filing events against the wrong set. The set strip
    # under the score is inside the fragment and owns this now.

    st.sidebar.subheader("Video")
    st.sidebar.toggle("Show video", key="show_video")
    if st.session_state.show_video:
        st.sidebar.radio(
            "Layout", ["On top", "Side by side"], key="video_layout", horizontal=True,
            help="On top gives the player the full width of the window.",
        )
        if st.session_state.video_layout == "On top":
            st.sidebar.slider("Height", 240, 800, step=20, key="video_height")
        else:
            st.sidebar.slider(
                "Width", 3, 7, key="video_width", help="How much of the row the video takes."
            )


def sidebar_roster(roster: pd.DataFrame) -> None:
    st.sidebar.subheader("Roster")
    with st.sidebar.expander("Edit roster", expanded=not len(roster)):
        edited = st.data_editor(
            roster if len(roster) else pd.DataFrame(columns=schema.ROSTER_COLUMNS),
            num_rows="dynamic",
            width="stretch",
            hide_index=True,
            column_config={
                "player_id": st.column_config.TextColumn("id", help="left blank = auto"),
                "number": st.column_config.NumberColumn("#", min_value=0, max_value=99, step=1),
                "active": st.column_config.CheckboxColumn("active", default=True),
            },
            key="roster_editor",
        )
        if st.button("Save roster", key="save_roster", width="stretch"):
            store.save_roster(edited)
            flash("success", "Roster saved")
            st.rerun()
        if st.session_state.spreadsheet is not None:
            title = st.session_state.mapping.get("roster", schema.TAB_ROSTER)
            col_a, col_b = st.columns(2)
            if col_a.button("⬇ From Sheets", key="roster_pull", width="stretch"):
                try:
                    store.save_roster(sheets.read_roster(st.session_state.spreadsheet, title))
                    flash("success", f"Roster loaded from “{title}”")
                    st.rerun()
                except Exception as exc:
                    flash("error", f"Could not read roster: {exc}")
            if col_b.button("⬆ To Sheets", key="roster_push", width="stretch"):
                try:
                    sheets.write_roster(st.session_state.spreadsheet, title, store.load_roster())
                    flash("success", f"Roster written to “{title}”")
                except Exception as exc:
                    flash("error", f"Could not write roster: {exc}")


# --- main panels ------------------------------------------------------------

def scoreboard(match: dict, set_no: int) -> None:
    us_key, them_key = score_keys(match["match_id"], set_no)
    left, mid_a, mid_b, right = st.columns([3, 1, 1, 2])
    left.markdown(
        f"### {match['opponent']}  \n{match['date']} · {match['home_away']} · **set {set_no}**"
    )
    mid_a.number_input("Us", min_value=0, step=1, key=us_key)
    mid_b.number_input("Them", min_value=0, step=1, key=them_key)
    right.markdown("&nbsp;", unsafe_allow_html=True)
    bump_us, bump_them = right.columns(2)
    bump_us.button(
        "+1 us", key=f"bump::{us_key}", on_click=cb_bump, args=(us_key, 1), width="stretch",
        help="Point from an opponent error - no player event recorded",
    )
    bump_them.button(
        "+1 them", key=f"bump::{them_key}", on_click=cb_bump, args=(them_key, 1),
        width="stretch", help="Opponent point",
    )


def set_navigator(match: dict, set_no: int, match_events: pd.DataFrame) -> None:
    """Move between sets without going to the sidebar, and know when one is done.

    A set is 'done' once what you entered matches the official score for it, so
    finishing a set and moving on is one glance and one click.
    """
    entered = stats.per_set_scores(match_events)
    entered_by_set = {
        int(row["set_no"]): f"{int(row['score_us'])}-{int(row['score_them'])}"
        for row in entered.to_dict("records")
    }
    official = [
        part.strip() for part in str(match.get("official_sets", "") or "").split(",")
        if part.strip()
    ]
    official_by_set = {index: value for index, value in enumerate(official, start=1)}

    # Always all five. Guessing how many sets a match has leaves sets 4 and 5
    # unreachable before it has been played.
    columns = st.columns(6)
    for index, number in enumerate(range(1, 6)):
        mine = entered_by_set.get(number)
        theirs = official_by_set.get(number)
        if mine and theirs and mine == theirs:
            label = f"Set {number} ✅"
        elif mine and theirs:
            label = f"Set {number} · {mine} vs {theirs}"
        elif mine:
            label = f"Set {number} · {mine}"
        else:
            label = f"Set {number}"
        columns[index].button(
            label,
            key=f"goto_set::{number}",
            on_click=cb_goto_set,
            args=(number,),
            width="stretch",
            type="primary" if number == set_no else "secondary",
            help=f"Profixio {theirs} · entered {mine or '—'}" if theirs else None,
        )

    mine = entered_by_set.get(set_no)
    theirs = official_by_set.get(set_no)
    matches_official = bool(mine and theirs and mine == theirs)
    columns[-1].button(
        f"Set {set_no + 1} →" if set_no < 5 else "Last set",
        key="next_set",
        on_click=cb_goto_set,
        args=(min(5, set_no + 1),),
        width="stretch",
        disabled=set_no >= 5,
        type="primary" if matches_official else "secondary",
        help="Nothing marks a set finished - it shows ✅ once what you entered "
             "matches the official score. The line-up carries over.",
    )
    if matches_official:
        st.caption(f"Set {set_no} matches the official {theirs} — ready for the next one.")


def video_panel(match: dict, max_height: int = 2000) -> None:
    """The player, plus the in-panel entry box that carries the video clock."""
    url = match.get("video_url", "") or ""
    video_id = video.parse_youtube_id(url)

    with st.expander("Match video URL", expanded=not url):
        st.text_input(
            "YouTube URL", value=url, key="video_url_input", placeholder="https://youtu.be/…",
            label_visibility="collapsed",
        )
        st.button(
            "Link video", key="save_video_url", on_click=cb_save_video_url, args=(match,),
            width="stretch",
        )
        if url and not video_id:
            st.error("No YouTube video id found in that URL.")
        elif video_id:
            st.caption(
                f"[Open on YouTube](https://youtu.be/{video_id}) — private videos cannot be "
                "embedded, unlisted works."
            )

    return video.video_panel(video_id, max_height=max_height)


def player_label(player: dict, squad: list) -> str:
    """`#1 Michelle` - full names make the buttons three lines tall.

    Falls back to a surname initial only if two of the called-up players share
    a first name.
    """
    parts = str(player.get("name", "")).split()
    first = parts[0] if parts else ""
    clashes = [p for p in squad if str(p.get("name", "")).split()[:1] == [first]]
    if len(clashes) > 1 and len(parts) > 1:
        first = f"{first} {parts[1][0]}."
    return f"#{int(player['number'])} {first}".strip()


def _player_row(squad: list, match: dict, caption: str, callback, exclude=None) -> None:
    st.caption(caption)
    shown = [p for p in squad if exclude is None or int(p["number"]) != int(exclude)]
    per_row = min(8, max(4, len(shown)))
    columns = st.columns(per_row)
    for index, player in enumerate(shown):
        columns[index % per_row].button(
            player_label(player, squad),
            key=f"player::p{int(player['number'])}" if exclude is None
                else f"target::p{int(player['number'])}",
            on_click=callback,
            args=(match, player),
            width="stretch",
        )


def entry_buttons(roster: pd.DataFrame, match: dict) -> None:
    """Action, then result, then player.

    The action row never changes, so it is always in the same place; the player
    row - the one that differs between matches - comes last, by which point the
    name is already known.
    """
    players = store.squad_players(roster, match, int(st.session_state.set_no))
    if not len(players):
        st.warning("Nobody called up. Reopen Match setup to pick the squad.")
        return
    squad = players.to_dict("records")

    st.caption("Action")
    action_columns = st.columns(len(schema.ACTION_ORDER) + 1)
    for index, action in enumerate(schema.ACTION_ORDER):
        action_columns[index].button(
            action.title(),
            key=f"action::{action}",
            on_click=cb_pick_action,
            args=(action,),
            width="stretch",
            type="primary" if st.session_state.sel_action == action else "secondary",
        )
    action_columns[-1].button(
        "✕", key="cancel", on_click=cb_clear_selection, width="stretch", help="Start over"
    )

    action = st.session_state.sel_action
    if not action:
        st.caption("Pick an action to see its results.")
        return

    st.caption(f"Result · {action.title()}")
    results = schema.ACTIONS[action]
    result_columns = st.columns(len(results))
    for index, result in enumerate(results):
        result_columns[index].button(
            schema.result_label(action, result),
            key=f"result::{action}::{result}",
            on_click=cb_pick_result,
            args=(result,),
            width="stretch",
            type="primary" if st.session_state.sel_result == result else "secondary",
        )

    result = st.session_state.sel_result
    if not result:
        return

    # Which players already have this from the official record, shown before
    # you tap rather than after - the point is to prevent the double entry, not
    # to report it once it has happened.
    if schema.is_point(action, result):
        have = []
        for player in squad:
            count = store.protocol_count(
                match["match_id"], st.session_state.set_no, player["number"], action
            )
            if count:
                have.append(f"#{int(player['number'])}×{count}")
        if have:
            st.caption(
                f"The official protocol already has {action.lower()} points for "
                + " · ".join(have)
                + " — only add one if the protocol got it wrong."
            )

    assist = action == schema.SET and result == "assist"
    chosen = st.session_state.sel_player
    if not (assist and chosen):
        _player_row(squad, match, f"Player · {action.lower()} {result}", cb_pick_player)

    # An assist needs one more tap: who it was set to.
    if assist and chosen:
        _player_row(
            squad, match,
            f"#{chosen['number']} {chosen['name']} set it to…",
            cb_pick_target, exclude=chosen["number"],
        )

def entry_panel(roster: pd.DataFrame, match: dict) -> None:
    entry_buttons(roster, match)


def box_score(match_events: pd.DataFrame, matches: pd.DataFrame, match: dict) -> None:
    st.subheader("Box score")
    if not len(match_events):
        st.caption("Nothing entered yet.")
        return
    sources = set(str(s) for s in match_events["source"])
    if sources <= {schema.SOURCE_PROFIXIO}:
        st.info(
            "Official protocol only. It records scoring actions, so attempts, errors, "
            "receptions and digs are still missing \u2014 rates like hitting efficiency "
            "and pass rating are not meaningful until you have been through the video."
        )

    # Rates are worked out here for the screen only; the spreadsheet stores
    # counts and Looker does the arithmetic.
    players = stats.with_rates(stats.player_match_stats(match_events, matches))
    st.dataframe(
        players[BOX_SCORE_VIEW].sort_values("points", ascending=False),
        width="stretch",
        hide_index=True,
        column_config={
            "kill_pct": st.column_config.NumberColumn("kill %", format="%.3f"),
            "hitting_eff": st.column_config.NumberColumn("hit eff", format="%.3f"),
            "pass_rating": st.column_config.NumberColumn("pass", format="%.2f"),
            "player_num": st.column_config.NumberColumn("#"),
            "player_name": st.column_config.TextColumn("player"),
            "player_role": st.column_config.TextColumn("role"),
            "reception_count": st.column_config.NumberColumn("recept"),
            "attack_errors": st.column_config.NumberColumn("att err"),
            "serve_errors": st.column_config.NumberColumn("srv err"),
            "blocks": st.column_config.NumberColumn("blocks"),
        },
    )
    team = stats.with_rates(stats.team_match_stats(match_events, matches))
    if len(team):
        row = team.iloc[0]
        cols = st.columns(5)
        cols[0].metric("Points", f"{row['points']:.1f}")
        cols[1].metric("Hitting eff", f"{row['hitting_eff']:.3f}")
        cols[2].metric("Kills / errors", f"{int(row['kills'])} / {int(row['attack_errors'])}")
        cols[3].metric("Aces / srv errors", f"{int(row['aces'])} / {int(row['serve_errors'])}")
        cols[4].metric("Pass rating", f"{row['pass_rating']:.2f}")
        official_comparison(match, row, match_events)


def recent_events(match_events: pd.DataFrame) -> None:
    """The last dozen, newest first - what you just did is at the top."""
    st.subheader("Recent")
    if not len(match_events):
        st.caption("Nothing entered yet.")
        return
    for event in match_events.to_dict("records"):
        line, undo = st.columns([7, 1])
        line.write(
            f"S{event['set_no']} · #{event['player_num']} {event['player_name']} · "
            f"**{event['action'].lower()}** {event['action_result']}"
            f"  `{event['score_us']}-{event['score_them']}`"
        )
        undo.button(
            "✕", key=f"undo::{event['event_id']}", on_click=cb_undo, args=(event["event_id"],)
        )


def full_editor(match_events: pd.DataFrame, match_id: str) -> None:
    with st.expander(f"Edit all {len(match_events)} events of this match"):
        if not len(match_events):
            st.caption("Nothing to edit.")
            return
        # Newest first, in the order you registered them - the same order as
        # Recent above, so the thing you just got wrong is the first row of
        # both. Not (set, seq): seq restarts every set, so that would bury
        # tonight's work under set 1. `recorded_at` is not shown; it only sorts.
        display = store.newest_first(match_events, match_id)[schema.EVENT_COLUMNS].copy()
        editable = ["set_no", "seq", "player_num", "action", "action_result"]
        all_results = sorted({r for results in schema.ACTIONS.values() for r in results})
        edited = st.data_editor(
            display,
            width="stretch",
            hide_index=True,
            num_rows="fixed",
            disabled=[c for c in display.columns if c not in editable],
            column_config={
                "action": st.column_config.SelectboxColumn(options=list(schema.ACTIONS)),
                "action_result": st.column_config.SelectboxColumn(options=all_results),
                "player_num": st.column_config.NumberColumn("#", min_value=0, max_value=99),
            },
            key=f"editor::{match_id}",
        )
        # Stashed for the callback, the way the squad and duplicate editors do
        # it: a callback runs before the rerun, so it sees what was on screen
        # when the button was pressed rather than a freshly rendered table.
        st.session_state[f"editor_edit::{match_id}"] = edited
        col_save, col_download = st.columns(2)
        col_save.button("Save edits", key="save_edits", width="stretch",
                        on_click=cb_save_edits, args=(match_id,))
        col_download.download_button(
            "Download this match (CSV)",
            # Deliberately the other way round: a log you read elsewhere runs
            # forwards through the match, set 1 first.
            match_events[schema.EVENT_COLUMNS].to_csv(index=False),
            file_name=f"{match_id}.csv",
            mime="text/csv",
            width="stretch",
        )


# What a row claims happened. Change any of it and a previous "yes, keep this"
# was about a different row, so the review decision is withdrawn.
CLAIM = ("set_no", "player_num", "action", "action_result")


def cb_save_edits(match_id: str) -> None:
    edited = st.session_state.get(f"editor_edit::{match_id}")
    if edited is None or not len(edited):
        return
    save_edits(edited, match_id)


def save_edits(edited: pd.DataFrame, match_id: str) -> None:
    """Re-validate the edited rows and write back the ones that actually changed.

    The name is resolved from the match line-up, never from the roster. The
    roster is current; the line-up is the record of who wore which shirt on the
    day. Looking a number up in the roster is how points scored by #4 in
    September came back stamped with the name of whoever wears #4 now.
    """
    problems = []
    rows = []
    for position, row in enumerate(edited.to_dict("records"), start=1):
        try:
            action, result = schema.validate(row["action"], row["action_result"])
        except schema.InvalidEvent as exc:
            problems.append(f"row {position}: {exc}")
            continue
        # Resolve against the row's own set, which is itself editable. A number
        # the line-up does not mention keeps the name it already carries rather
        # than being blanked or guessed at.
        names = store.names_for_set(match_id, int(row["set_no"]))
        row["player_name"] = names.get(int(row["player_num"]), row["player_name"])
        row["action"], row["action_result"] = action, result
        row["is_point"] = schema.is_point(action, result)
        rows.append(row)

    if problems:
        flash("error", "Not saved - " + "; ".join(problems))
        return

    events = store.load_events()
    before = events.set_index("event_id")
    changed = []
    for row in rows:
        was = before.loc[row["event_id"]] if row["event_id"] in before.index else None
        if was is None:
            continue
        fields = ["player_name", "is_point"] + list(CLAIM)
        if all(str(was[field]) == str(row[field]) for field in fields):
            continue   # untouched: leave its synced and reviewed flags alone
        row["synced"] = False   # edited rows need re-pushing
        if any(str(was[field]) != str(row[field]) for field in CLAIM):
            row["reviewed"] = False
        changed.append(row)

    if not changed:
        flash("success", "No changes to save.")
        return

    updated = pd.DataFrame(changed)
    changed_ids = set(updated["event_id"])
    events = store.concat_frames([events[~events["event_id"].isin(changed_ids)], updated])
    store.save_events(events)
    flash("success", f"Saved {len(changed)} event(s)")


# --- match setup ------------------------------------------------------------

def cb_sync_profixio() -> None:
    settings = config.profixio()
    try:
        html = profixio.fetch_team_page(
            settings["league_id"], settings["team_id"], settings["key"]
        )
        players = profixio.parse_roster(html)
        fixtures = profixio.parse_fixtures(html, settings["team_name"])
        store.merge_profixio_roster(players)
        store.merge_profixio_fixtures(fixtures)
        played = sum(1 for f in fixtures if f["played"])
        flash("success", f"Profixio: {len(fixtures)} fixtures ({played} played), "
                         f"{len(players)} players")
    except profixio.ProfixioError as exc:
        flash("error", str(exc))


def import_protocol(match: dict, pdf_bytes: bytes) -> None:
    """Replace this match's imported events with a freshly parsed protocol."""
    try:
        protocol = profixio.parse_protocol(profixio.extract_pdf_text(pdf_bytes))
        team = config.team_name()
        summary = profixio.protocol_summary(protocol, team)
        events = profixio.protocol_to_events(
            protocol, team, match, store.load_roster()
        )
        if not events:
            flash("error", f"No {team} events found in that protocol - wrong match?")
            return
        store.replace_profixio_events(match["match_id"], events)
        store.restamp_players(match["match_id"])  # imported rows get the line-up's
        store.restamp_roles(match["match_id"])    # names and roles
        flash("success",
              f"{summary['rows']} rows → {len(events)} events · "
              f"{summary['points_for']}-{summary['points_against']} points · "
              f"result {summary['result']}")
    except profixio.ProfixioError as exc:
        flash("error", str(exc))


def cb_import_file(match: dict, path) -> None:
    try:
        import_protocol(match, profixio.read_protocol_file(path))
    except profixio.ProfixioError as exc:
        flash("error", str(exc))


def cb_import_upload(match: dict, upload_key: str) -> None:
    uploaded = st.session_state.get(upload_key)
    if uploaded is None:
        return
    import_protocol(match, uploaded.getvalue())


def protocol_section(match: dict, match_events: pd.DataFrame) -> None:
    profixio_id = str(match.get("profixio_match_id", "") or "")
    st.markdown("**Official protocol**")
    if not profixio_id:
        st.caption("No Profixio match linked, so there is no protocol to import.")
        return

    imported = match_events[match_events["source"] == schema.SOURCE_PROFIXIO]
    if len(imported):
        st.success(f"{len(imported)} events already imported.")

    found = profixio.find_downloaded_protocol(profixio_id)
    if found is not None:
        st.button(f"⬇ Import {found.name}", key="import_found", type="primary",
                  width="stretch", on_click=cb_import_file, args=(match, found))

    upload_key = f"upload::{match['match_id']}"
    uploaded = st.file_uploader("or drop the Arbetsprotokoll PDF", type="pdf", key=upload_key)
    if uploaded is not None:
        st.button("Import uploaded protocol", key="import_upload", width="stretch",
                  on_click=cb_import_upload, args=(match, upload_key))

    url = profixio.protocol_url(config.profixio()["league_id"], profixio_id)
    st.caption(
        f"[Download the Arbetsprotokoll]({url}) — Profixio puts a bot check on this "
        "link, so it has to be saved from the browser. Once it is in Downloads it is "
        "picked up automatically."
    )


def role_editor(match_id: str, set_no: int, players: list, key: str) -> None:
    """Who is playing which role in one set.

    Roles live per (match, set) because players move between them mid-match,
    and the whole point of recording them is to compare a player's numbers
    across the roles they actually played.
    """
    if not players:
        st.caption("Nobody called up yet.")
        return

    current = store.roles_for_set(match_id, set_no)
    frame = pd.DataFrame([
        {
            "player_num": int(player["number"]),
            "player_name": player["name"],
            "player_role": current.get(
                int(player["number"]), player.get("position", "") or ""
            ),
        }
        for player in players
    ])
    rows = frame.to_dict("records")
    st.data_editor(
        frame,
        key=key,
        hide_index=True,
        width="stretch",
        on_change=cb_roles_changed,
        args=(match_id, set_no, rows, key),
        column_config={
            "player_num": st.column_config.NumberColumn("#", disabled=True),
            "player_name": st.column_config.TextColumn("player", disabled=True),
            "player_role": st.column_config.SelectboxColumn(
                "role", options=[""] + schema.ROLES, required=False
            ),
        },
    )
    st.caption("Changes save as you make them.")


def ensure_set_lineup(match_id: str, set_no: int, roster: pd.DataFrame, match: dict) -> None:
    """Make sure the set has a line-up, and that everyone called up is in it.

    Most sets start the same as the one before, so the previous set is carried
    forward. It is then topped up with anyone in the squad who is missing -
    otherwise a player who has not touched the ball yet would have no button.
    """
    set_no = int(set_no)
    existing = store.match_lineup(match_id, set_no).to_dict("records")

    if not existing:
        for previous in range(set_no - 1, 0, -1):
            if len(store.match_lineup(match_id, previous)):
                store.copy_lineup(match_id, previous, set_no)
                existing = store.match_lineup(match_id, set_no).to_dict("records")
                break

    rows = [
        {k: row[k] for k in ("player_num", "player_name", "player_role")}
        for row in existing
    ]
    present = {str(row["player_name"]) for row in rows}
    taken = {int(row["player_num"]) for row in rows}

    called = set(store.squad_numbers(match))
    candidates = roster[roster["number"].isin(called)] if called else store.active_players(roster)
    for player in candidates.sort_values("number").to_dict("records"):
        # Skip on either key. A squad recorded in last season's numbering can
        # otherwise collide with whoever wears that shirt now.
        if player["name"] in present or int(player["number"]) in taken:
            continue
        present.add(player["name"])
        taken.add(int(player["number"]))
        rows.append({
            "player_num": int(player["number"]),
            "player_name": player["name"],
            "player_role": player.get("position", "") or "",
        })

    if rows and len(rows) != len(existing):
        store.set_lineup(match_id, set_no, sorted(rows, key=lambda r: int(r["player_num"])))
    elif not existing and rows:
        store.set_lineup(match_id, set_no, rows)


def cb_apply_duplicates(match_id: str, set_no: int) -> None:
    """Remove what was unticked, and remember everything that was kept.

    Recording the decision is the point. Deleting used to be the only thing
    that stuck, so a correction you chose to keep was offered for deletion
    again on the next rerun, and again after that.
    """
    edited = st.session_state.get(f"dupes_edit::{match_id}::{set_no}")
    if edited is None or not len(edited):
        return
    keeping = edited["keep"].astype(bool)
    dropping = edited[~keeping]["event_id"]
    store.mark_reviewed(edited[keeping]["event_id"])
    if not len(dropping):
        flash("success", f"Set {set_no} reviewed - nothing unticked, nothing removed.")
        return
    store.drop_events(dropping)
    flash("success",
          f"Removed {len(dropping)} event(s) from set {set_no}; "
          f"kept {int(keeping.sum())}.")


def dupe_note(row) -> str:
    """One sentence about a row, saying the same thing on every row of a group.

    It used to read "the other source has 4" on your row and "the other source
    has 6" on the protocol's, which are two true statements that look like a
    contradiction. Both totals, stated the same way, is one fact you can act on.
    """
    if row["reviewed"]:
        return "✓ kept on review"
    if row["source"] == schema.SOURCE_MANUAL and not row["matches"]:
        return "protocol has none - looks like a correction"
    return f"protocol {int(row['n_protocol'])} · you {int(row['n_manual'])}"


def review_duplicates(match: dict) -> None:
    """Point-scoring events a set holds twice: once officially, once by hand.

    Only these can be duplicates - the protocol records nothing else, so a
    reception or a dig can never collide with it and is never shown here.
    Nothing is removed until Apply, and every row is yours to tick.
    """
    match_id = match["match_id"]
    st.markdown("**Review duplicates**")
    if not store.has_profixio_events(match_id):
        st.caption("No official protocol imported, so nothing can be a duplicate.")
        return

    set_no = st.selectbox("Set", [1, 2, 3, 4, 5], key=f"dupes_set::{match_id}")
    candidates = store.duplicate_candidates(match_id, int(set_no))
    if not len(candidates):
        st.caption(f"Set {set_no} has no point-scoring events to compare.")
        return

    frame = pd.DataFrame([
        {
            "keep": bool(row["keep"]),
            "source": "protocol" if row["source"] == schema.SOURCE_PROFIXIO else "you",
            "player": f"#{int(row['player_num'])} {row['player_name']}",
            "action": f"{row['action'].lower()} {row['action_result']}",
            "score": (f"{int(row['score_us'])}-{int(row['score_them'])}"
                      if row["source"] == schema.SOURCE_PROFIXIO else ""),
            "note": dupe_note(row),
            "event_id": row["event_id"],
        }
        for row in candidates.to_dict("records")
    ])

    edited = st.data_editor(
        frame,
        key=f"dupes::{match_id}::{set_no}",
        hide_index=True,
        width="stretch",
        column_config={
            "keep": st.column_config.CheckboxColumn("keep", width="small"),
            "source": st.column_config.TextColumn("from", disabled=True),
            "player": st.column_config.TextColumn("player", disabled=True),
            "action": st.column_config.TextColumn("action", disabled=True),
            "score": st.column_config.TextColumn("at", disabled=True),
            "note": st.column_config.TextColumn("note", disabled=True),
            "event_id": None,
        },
    )
    st.session_state[f"dupes_edit::{match_id}::{set_no}"] = edited

    dropping = int((~edited["keep"].astype(bool)).sum())
    settled = int(candidates["reviewed"].astype(bool).sum())
    already = f" {settled} already reviewed." if settled else ""
    st.caption(
        f"{len(edited)} point-scoring events in set {set_no}.{already} "
        f"Apply would remove {dropping} and mark the rest reviewed, so they "
        "stop coming back. Receptions, digs, attempts, errors and sets are "
        "never shown here and are never touched."
    )
    unsettled = int((~candidates["reviewed"].astype(bool)).sum())
    st.button(
        f"Apply — remove {dropping}", key=f"dupes_apply::{match_id}::{set_no}",
        on_click=cb_apply_duplicates, args=(match_id, int(set_no)),
        width="stretch",
        # Enabled with nothing to remove, because Apply is also how you say
        # "these are all fine" and stop being asked.
        disabled=dropping == 0 and unsettled == 0,
    )


def squad_editor(roster: pd.DataFrame, match: dict, set_no: int = 1) -> None:
    """Who is playing, wearing what, in which role - one table.

    Call-up, shirt number and role used to be two separate controls listing the
    same people. They are one now, because they are one decision.
    """
    match_id = match["match_id"]
    if not len(roster):
        st.caption("No roster yet. Refresh from Profixio.")
        return

    roles = store.roles_for_set(match_id, set_no)
    lineup = store.match_lineup(match_id, set_no)
    records = lineup.to_dict("records") if len(lineup) else []
    # Matched by name, not number: a player who changed shirt between matches
    # would otherwise silently drop out of a squad she is already in.
    numbered = {str(r["player_name"]): int(r["player_num"]) for r in records}
    named_roles = {str(r["player_name"]): r["player_role"] for r in records}
    called_names = set(numbered)
    called_numbers = set(store.squad_numbers(match))

    # Where a line-up exists it is the authority on who played and what they
    # wore; the roster only supplies anyone not in it yet. Otherwise a player
    # whose shirt has since changed hands gets overwritten by whoever has it
    # now, every time this screen is opened.
    players = [
        {"number": int(r["player_num"]), "name": r["player_name"],
         "position": r["player_role"], "active": True}
        for r in records
    ]
    present = {p["name"] for p in players}
    players += [
        p for p in roster.sort_values("number").to_dict("records")
        if p["name"] not in present
    ]
    frame = pd.DataFrame([
        {
            "called": (player["name"] in called_names) if called_names
                      else (int(player["number"]) in called_numbers) if called_numbers
                      else bool(player["active"]),
            "player_num": numbered.get(player["name"], int(player["number"])),
            "player_name": player["name"],
            "player_role": named_roles.get(
                player["name"],
                roles.get(int(player["number"]), player.get("position", "") or ""),
            ),
        }
        for player in players
    ])

    edited = st.data_editor(
        frame,
        key=f"squad::{match_id}::{set_no}",
        hide_index=True,
        width="stretch",
        column_config={
            "called": st.column_config.CheckboxColumn("✓", width="small"),
            "player_num": st.column_config.NumberColumn(
                "#", min_value=0, max_value=99, step=1,
                help="Shirt worn in this match - change it here if it differs",
            ),
            "player_name": st.column_config.TextColumn("player", disabled=True),
            "player_role": st.column_config.SelectboxColumn(
                "role", options=[""] + schema.ROLES, required=False
            ),
        },
    )
    picked = edited[edited["called"].astype(bool)]
    st.caption(f"{len(picked)} of {len(edited)} called up")
    st.session_state[f"squad_edit::{match_id}"] = edited


def save_squad(match_id: str, set_no: int = 1) -> None:
    """Persist the one table: squad numbers on the match, roles on the set."""
    edited = st.session_state.get(f"squad_edit::{match_id}")
    if edited is None or not len(edited):
        return
    picked = edited[edited["called"].astype(bool)]
    store.set_squad(match_id, [int(n) for n in picked["player_num"]])
    store.set_lineup(match_id, set_no, [
        {
            "player_num": int(row["player_num"]),
            "player_name": row["player_name"],
            "player_role": str(row["player_role"] or ""),
        }
        for row in picked.to_dict("records")
    ])
    store.restamp_players(match_id, set_no)
    store.restamp_roles(match_id, set_no)


def default_match_id(matches: pd.DataFrame) -> str:
    """The match you most likely want: the last one played, else the next one up.

    Matches are stored newest-first, so falling back to row zero would land on
    the final fixture of the season - never the useful answer.
    """
    if not len(matches):
        return ""
    played = matches[matches["official_result"].astype(str) != ""]
    if len(played):
        return played.sort_values("date").iloc[-1]["match_id"]
    today = date.today().isoformat()
    upcoming = matches[matches["date"].astype(str) >= today].sort_values("date")
    if len(upcoming):
        return upcoming.iloc[0]["match_id"]
    return matches.sort_values("date").iloc[-1]["match_id"]


def setup_screen(matches: pd.DataFrame, roster: pd.DataFrame) -> None:
    st.subheader("Match setup")

    if not len(matches):
        st.info("No matches yet. Pull the season from Profixio to get started.")
        st.button("↻ Refresh from Profixio", key="sync_empty",
                  on_click=cb_sync_profixio, type="primary")
        return

    options = list(matches["match_id"])
    labels = {}
    for row in matches.itertuples():
        result = f" · {row.official_result}" if row.official_result else ""
        labels[row.match_id] = f"{row.date} · {row.opponent} ({row.home_away}){result}"
    current = st.session_state.match_id or default_match_id(matches)
    index = options.index(current) if current in options else 0
    chosen = st.selectbox(
        "Match", options, index=index, format_func=lambda m: labels.get(m, m), key="setup_match"
    )
    st.session_state.match_id = chosen
    match = matches[matches["match_id"] == chosen].iloc[0].to_dict()
    match_events = store.match_events(store.load_events(), chosen)

    left, right = st.columns(2)
    with left:
        if match.get("official_result"):
            st.markdown(
                f"**Official result** `{match['official_result']}`  \n"
                f"{match.get('official_sets', '')}"
            )
        st.text_input(
            "YouTube URL", value=match.get("video_url", "") or "",
            key="video_url_input", placeholder="https://youtu.be/…",
        )
        st.button("Save video URL", key="save_video_setup",
                  on_click=cb_save_video_url, args=(match,), width="stretch")
        st.divider()
        protocol_section(match, match_events)
        st.divider()
        review_duplicates(match)

    with right:
        st.markdown("**Called up**")
        squad_editor(roster, match)
        st.divider()
        st.button("↻ Refresh from Profixio", key="sync_profixio",
                  on_click=cb_sync_profixio, width="stretch")
        with st.expander("➕ Match not in Profixio"):
            st.date_input("Date", value=date.today(), key="new_date")
            st.text_input("Opponent", key="new_opponent")
            st.selectbox("Home / away", ["home", "away", "neutral"], key="new_home_away")
            st.button("Create match", key="create_match",
                      on_click=cb_new_match, width="stretch")
        st.button("Start entering →", key="start_entering", type="primary",
                  width="stretch", on_click=cb_start_entering, args=(chosen,))


def official_comparison(match: dict, team_row, match_events: pd.DataFrame) -> None:
    """Profixio's official set scores beside what the entered events add up to.

    Set by set rather than as one lump, so a set can be checked the moment it
    is finished instead of only discovering at the end of the match that one of
    them went in under the wrong number.
    """
    official_sets = [
        part.strip() for part in str(match.get("official_sets", "") or "").split(",")
        if part.strip()
    ]
    official_result = str(match.get("official_result", "") or "")
    if not official_sets and not official_result:
        return

    entered = stats.per_set_scores(match_events)
    entered_by_set = {
        int(row["set_no"]): f"{int(row['score_us'])}-{int(row['score_them'])}"
        for row in entered.to_dict("records")
    }

    tick, warn, blank = "✅", "⚠️", "—"
    rows, all_agree = [], True
    for index, official in enumerate(official_sets, start=1):
        mine = entered_by_set.get(index, "")
        if not mine:
            rows.append((f"Set {index}", official, blank, "not entered yet"))
            all_agree = False
            continue
        agrees = mine == official
        all_agree = all_agree and agrees
        rows.append((f"Set {index}", official, mine, tick if agrees else warn))

    # Sets entered that the official record doesn't have at all.
    for set_no in sorted(set(entered_by_set) - set(range(1, len(official_sets) + 1))):
        rows.append((f"Set {set_no}", blank, entered_by_set[set_no], warn))
        all_agree = False

    result_mine = f"{int(team_row['sets_won'])}-{int(team_row['sets_lost'])}"
    if official_result:
        agrees = result_mine == official_result
        all_agree = all_agree and agrees
        rows.append(("Result", official_result, result_mine, tick if agrees else warn))

    with st.container(border=True):
        st.markdown(f"**Official vs entered** {tick if all_agree else warn}")
        st.dataframe(
            pd.DataFrame(rows, columns=["Set", "Profixio", "Entered", "Match"]),
            hide_index=True,
            width="stretch",
        )
        if not all_agree:
            st.caption(
                "A set that doesn't match usually means events went in under the wrong "
                "set number, or that set isn't finished yet."
            )


# --- workspace --------------------------------------------------------------

@st.fragment
def workspace(match: dict, roster: pd.DataFrame, matches: pd.DataFrame) -> None:
    """Everything that reruns when you record an event.

    Isolating this in a fragment keeps the sidebar and the page header out of
    the rerun, which matters because the video component is in here: fewer
    render passes, no chance of the player being disturbed by unrelated work.
    """
    # A fragment keeps the arguments it was called with, so anything saved from
    # inside it - the video URL, the squad, the roles - would still read back as
    # it was at the last full rerun. Re-read the match row instead of trusting
    # what was passed in.
    match_id = match["match_id"]
    matches = store.load_matches()
    current = matches[matches["match_id"] == match_id]
    if len(current):
        match = current.iloc[0].to_dict()

    set_no = int(st.session_state.set_no)
    show_video = st.session_state.show_video
    # Set here, not inside the panel: collapsing the video must not stop events
    # from carrying their deep link.
    st.session_state.video_url_current = match.get("video_url", "") or ""

    # Seed the score before anything can record: a submission arriving from the
    # video panel is handled inline, not in a callback, so unlike the button
    # grid it reaches commit() during this very first script run.
    events = store.load_events()
    ensure_score_state(events, match_id, set_no)
    ensure_set_lineup(match_id, set_no, roster, match)

    on_top = st.session_state.video_layout == "On top"
    if show_video and on_top:
        video_panel(match, max_height=int(st.session_state.video_height))
    elif show_video:
        share = int(st.session_state.video_width)
        left, right = st.columns([10 - share, share])
        with right:
            video_panel(match)

    match_events = store.match_events(events, match_id)

    if st.session_state.flash:
        kind, message = st.session_state.flash
        (st.success if kind == "success" else st.error)(message)
        st.session_state.flash = None

    if show_video and on_top:
        # Everything you touch while watching, before anything else claims the
        # space. st.columns() reserves its row at the point it is called, so the
        # box score must not be created until the buttons are on screen.
        st.html(TIGHTEN_ENTRY)
        with st.container(key="entry_strip"):
            entry_buttons(roster, match)
        scoreboard(match, set_no)
        set_navigator(match, set_no, match_events)
        with st.expander(f"Roles · set {set_no}"):
            role_editor(
                match_id, set_no,
                store.squad_players(roster, match, set_no).to_dict("records"),
                key=f"roles::{match_id}::{set_no}",
            )
        st.divider()
        left, right = st.columns([3, 2])
    elif not show_video:
        left, right = st.columns([3, 2])

    with left:
        if not (show_video and on_top):
            scoreboard(match, set_no)
            set_navigator(match, set_no, match_events)
            st.divider()
            entry_panel(roster, match)
            with st.expander(f"Roles · set {set_no}"):
                role_editor(
                    match_id, set_no,
                    store.squad_players(roster, match).to_dict("records"),
                    key=f"roles::{match_id}::{set_no}",
                )
            st.divider()
        box_score(match_events, matches, match)

    with right:
        recent_events(store.newest_first(events, match_id, limit=12))

    full_editor(match_events, match_id)


# --- page -------------------------------------------------------------------

def main() -> None:
    init_state()
    roster = store.load_roster()
    matches = store.load_matches()
    events = store.load_events()

    sidebar_branding()

    if LOGO.exists():
        crest, title = st.columns([1, 11])
        crest.image(str(LOGO), width=64)
        title.title(f"{config.club_name()} · Volleyball Stats")
    else:
        st.title(f"🏐 {config.club_name()} · Volleyball Stats")

    sidebar_connection()
    sidebar_match(matches)
    sidebar_roster(roster)
    st.sidebar.divider()
    sidebar_push(events)

    if st.session_state.flash:
        kind, message = st.session_state.flash
        (st.success if kind == "success" else st.error)(message)
        if kind == "error" and st.session_state.get("auth_command"):
            st.code(st.session_state.auth_command, language="bash")
        st.session_state.flash = None

    match_id = st.session_state.match_id
    known = match_id and len(matches[matches["match_id"] == match_id])

    # The setup gate: pick the match, the video and the squad before entering.
    if not known or st.session_state.setup_done_for != match_id:
        setup_screen(matches, roster)
        return

    match = matches[matches["match_id"] == match_id].iloc[0].to_dict()
    workspace(match, roster, matches)


main()
