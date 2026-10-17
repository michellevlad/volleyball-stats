"""Pull the season from Profixio into the local buffer.

    python sync_profixio.py                 # fixtures + squad
    python sync_profixio.py --protocol-file a_32681384.pdf
    python sync_profixio.py --protocols     # every already-downloaded protocol

Profixio guards the protocol download with a bot check, so the PDF has to be
saved from the browser. Its filename carries the match id, so once it is in
Downloads it is picked up automatically.

Only Profixio-owned fields are written. Positions, active flags, video URLs,
squad call-ups and every event entered from video are left untouched.
"""

from __future__ import annotations

import sys

from volley import config, profixio, store


def sync_season() -> list:
    settings = config.profixio()
    print(f"Fetching {settings['team_name']} …")
    html = profixio.fetch_team_page(
        settings["league_id"], settings["team_id"], settings["key"]
    )

    players = profixio.parse_roster(html)
    store.merge_profixio_roster(players)
    print(f"  squad: {len(players)} players")

    fixtures = profixio.parse_fixtures(html, settings["team_name"])
    store.merge_profixio_fixtures(fixtures)
    played = [f for f in fixtures if f["played"]]
    print(f"  fixtures: {len(fixtures)} ({len(played)} played)")
    for fixture in fixtures:
        result = fixture["official_result"] or "—"
        print(f"    {fixture['date']} {fixture['home_away']:<5} "
              f"{fixture['opponent']:<22} {result}")
    return fixtures


def import_protocol(profixio_match_id: str, path=None) -> int:
    settings = config.profixio()
    matches = store.load_matches()
    row = matches[matches["profixio_match_id"].astype(str) == str(profixio_match_id)]
    if not len(row):
        print(f"No local match with Profixio id {profixio_match_id}. Sync first.")
        return 0
    match = row.iloc[0].to_dict()
    match_id = match["match_id"]

    if path is None:
        path = profixio.find_downloaded_protocol(profixio_match_id)
    if path is None:
        print(f"  {profixio_match_id}: no a_{profixio_match_id}.pdf found. Download it from")
        print(f"    {profixio.protocol_url(settings['league_id'], profixio_match_id)}")
        return 0
    pdf = profixio.read_protocol_file(path)
    protocol = profixio.parse_protocol(profixio.extract_pdf_text(pdf))
    summary = profixio.protocol_summary(protocol, settings["team_name"])
    events = profixio.protocol_to_events(
        protocol, settings["team_name"], match, store.load_roster()
    )
    store.replace_profixio_events(match_id, events)
    store.restamp_roles(match_id)
    print(f"  {match_id}: {summary['rows']} rows -> {len(events)} events, "
          f"{summary['points_for']}-{summary['points_against']} points, "
          f"result {summary['result']}")
    return len(events)


def main(argv: list) -> None:
    if "--protocol-file" in argv:
        position = argv.index("--protocol-file")
        if position + 1 >= len(argv):
            print("--protocol-file needs a path to a_<match id>.pdf")
            return
        path = argv[position + 1]
        found = __import__("re").search(r"a_(\d+)", str(path))
        if not found:
            print("Could not read a match id out of that filename.")
            return
        import_protocol(found.group(1), path)
        return

    fixtures = sync_season()
    if "--protocols" in argv:
        print("Importing official protocols …")
        for fixture in fixtures:
            if fixture["played"]:
                import_protocol(fixture["profixio_match_id"])


if __name__ == "__main__":
    main(sys.argv[1:])
