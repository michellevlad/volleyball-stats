"""Fill the local buffer with a demo match, to try the UI before a real one.

    python seed_demo.py                       # demo roster + one set of events
    python seed_demo.py --video <youtube-url>  # ...linked to a real match video
    python seed_demo.py --clear               # remove the demo match again

Only the demo match is touched - a season synced from Profixio is never
cleared, and an existing roster is left as it is.

Only touches data/ - nothing is sent to Google Sheets.
"""

from __future__ import annotations

import sys

import pandas as pd

from volley import schema, shorthand, store, video

ROSTER = [
    (7, "Ana", "OH"), (12, "Bea", "S"), (4, "Cyd", "MB"),
    (9, "Dana", "OP"), (2, "Elif", "L"), (15, "Fran", "MB"),
]

MATCH = {
    "match_id": "2026-09-27-lions", "date": "2026-09-27", "opponent": "Lions",
    "home_away": "home", "competition": "League", "sets_won": 0, "sets_lost": 0,
    "video_url": "",
    "notes": "demo data - delete with `python seed_demo.py --clear`",
}

# (squad slot, shorthand) - slots are resolved against whatever roster exists,
# so the demo works with the real Profixio squad or the placeholder one.
RALLY = [
    (0, "k"), (1, "as"), (0, "k"), (2, "bk"), (3, "e"),
    (4, "p"), (0, "ace"), (1, "as"), (0, "a0"), (2, "bt"),
    (3, "k"), (4, "ok"), (0, "se"), (1, "as"), (2, "k"),
    (4, "ok"), (3, "d"), (0, "k"), (1, "ste"), (4, "re"),
]


def clear() -> None:
    """Remove only the demo match. The synced season is left alone."""
    events = store.load_events()
    store.save_events(events[events["match_id"] != MATCH["match_id"]])
    matches = store.load_matches()
    store.save_matches(matches[matches["match_id"] != MATCH["match_id"]])
    print("Demo match removed.")


def seed(video_url: str = "") -> None:
    clear()   # seeding twice should give one demo match, not two
    if not len(store.load_roster()):
        store.save_roster(pd.DataFrame(
            [
                {"player_id": "", "number": number, "name": name,
                 "position": position, "active": number != 15}
                for number, name, position in ROSTER
            ]
        ))
    roster = store.load_roster()
    match = {**MATCH, "video_url": video_url}
    store.upsert_match(match)
    video_id = video.parse_youtube_id(video_url)

    squad = store.active_players(roster).to_dict("records")
    if len(squad) < 5:
        print("Need at least 5 active players. Run sync_profixio.py first.")
        return

    score_us = score_them = 0
    for index, (slot, code) in enumerate(RALLY):
        player = squad[slot % len(squad)]
        parsed = shorthand.parse(f"{int(player['number'])} {code}")
        if schema.is_point(parsed["action"], parsed["result"]):
            score_us += 1
        else:
            score_them += 1
        events = store.load_events()
        # Spread the demo events over the first few minutes of video.
        seconds = 30 + index * 22
        store.append_event(store.build_event(
            match_id=match["match_id"], set_no=1,
            seq=store.next_seq(events, match["match_id"], 1),
            player=player, action=parsed["action"], result=parsed["result"],
            score_us=score_us, score_them=score_them,
            video_seconds=seconds if video_id else None,
            video_link=video.video_link(video_id, seconds),
        ))
    linked = f" linked to {video_id}" if video_id else ""
    print(f"Seeded {len(RALLY)} events for {match['opponent']}{linked}. Run: streamlit run app.py")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear()
    else:
        url = ""
        if "--video" in sys.argv:
            position = sys.argv.index("--video")
            url = sys.argv[position + 1] if len(sys.argv) > position + 1 else ""
        seed(url)
