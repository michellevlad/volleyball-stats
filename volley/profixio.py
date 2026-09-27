"""Read the season from Profixio: fixtures, squad, and the official match protocol.

The team page is server-rendered, so plain HTTP is enough - no browser needed.
Each played match publishes an *Arbetsprotokoll* PDF containing the complete
official rally log: every point with its scorer, shirt number and running
score. That covers aces, attack points and block points exactly; attempts,
errors, receptions and digs are not in it and stay video work.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from . import schema, store

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) volleyball-stats"
TIMEOUT = 30

# --- the protocol's Swedish vocabulary --------------------------------------

EVENT_MAP = {
    "Serveess": (schema.SERVE, "ace"),
    "Anfall": (schema.ATTACK, "kill"),
    # The protocol only logs blocks that scored, so they are block points.
    "Block": (schema.BLOCK, "kill"),
}
OPPONENT_ERROR = "Motståndarmisstag"
NON_SCORING = ("Timeout", "Spelarbyte", "Startar med serve")

SET_START = re.compile(r"Start första set|(\d+):a set startades")
SET_END = re.compile(r"(\d+):a set är slut")
MATCH_END = "Matchen är slut"

SWEDISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "maj": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}


class ProfixioError(RuntimeError):
    """Network or parsing failure, with a message meant for the user."""


# --- urls and fetching ------------------------------------------------------

def team_url(league_id: str, team_id: str, key: str) -> str:
    return f"https://www.profixio.com/app/leagueid{league_id}/teams/{team_id}?k={key}"


def protocol_url(league_id: str, match_id: str, kind: str = "svbf_a") -> str:
    return f"https://www.profixio.com/app/leagueid{league_id}/match/{match_id}/protocol/{kind}"


def _get(url: str) -> bytes:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise ProfixioError(f"requests is not installed ({exc})") from exc
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        raise ProfixioError(f"Could not fetch {url}: {exc}") from exc
    return response.content


def fetch_team_page(league_id: str, team_id: str, key: str) -> str:
    return _get(team_url(league_id, team_id, key)).decode("utf-8", errors="replace")


# Profixio puts the protocol route behind Cloudflare's bot challenge (the team
# page is not), so it cannot be fetched by script. The PDF is downloaded from
# the browser instead - and its filename carries the match id, which is what
# makes picking it up again automatic.
CLOUDFLARE_HINT = (
    "Profixio protects the protocol download with a bot check, so it has to be "
    "downloaded from the browser.\n\n"
    "Open the link, save the PDF, and import it here - the file is named "
    "a_<match id>.pdf, so it will be found in your Downloads folder automatically."
)

PROTOCOL_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]


def fetch_protocol(league_id: str, match_id: str) -> bytes:
    """Try the direct download. Expect it to fail behind the bot check."""
    try:
        data = _get(protocol_url(league_id, match_id))
    except ProfixioError as exc:
        raise ProfixioError(f"{CLOUDFLARE_HINT}\n\n({exc})") from exc
    if not data.startswith(b"%PDF"):
        raise ProfixioError(CLOUDFLARE_HINT)
    return data


def find_downloaded_protocol(match_id: str, search_dirs=None) -> Path | None:
    """Locate an already-downloaded `a_<match id>.pdf`, newest first."""
    candidates = []
    for directory in (search_dirs if search_dirs is not None else PROTOCOL_DIRS):
        directory = Path(directory)
        if not directory.is_dir():
            continue
        candidates.extend(directory.glob(f"a_{match_id}*.pdf"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_protocol_file(path) -> bytes:
    path = Path(path)
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise ProfixioError(f"{path.name} is not a PDF.")
    return data


# --- html helpers -----------------------------------------------------------

def _lines(fragment: str) -> list[str]:
    """Visible text of an HTML fragment, one entry per element."""
    text = re.sub(r"<!--.*?-->", " ", fragment, flags=re.S)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]*>", "\n", text)
    return [line.strip() for line in text.split("\n") if line.strip()]


def _match_metadata(html: str) -> dict:
    """Date and result per match, from the Alpine blob that expands each card.

    The blob sits *before* the card it describes and names it via
    `expandmatch', <id>`, so it is keyed off that rather than position.
    """
    out = {}
    chunks = re.split(r"expandmatch',\s*(\d+)\s*\)", html)
    for index in range(1, len(chunks), 2):
        match_id, body = chunks[index], chunks[index + 1][:1200]
        stamp = re.search(r"timestamp:\s*(\d+)", body)
        played = re.search(r"hasResult:\s*(true|false)", body)
        out[match_id] = {
            "date": (
                datetime.datetime.fromtimestamp(int(stamp.group(1))).date().isoformat()
                if stamp else ""
            ),
            "played": bool(played and played.group(1) == "true"),
        }
    return out


# --- fixtures and roster ----------------------------------------------------

def parse_fixtures(html: str, team_name: str) -> list[dict]:
    """Every fixture on the season page, from our team's point of view."""
    metadata = _match_metadata(html)
    cards = re.split(r'wire:key="mc_mini_(\d+)"', html)
    fixtures = []

    for index in range(1, len(cards), 2):
        match_id, body = cards[index], cards[index + 1]
        lines = _lines(body[:9000])
        if match_id not in lines:
            continue
        rest = lines[lines.index(match_id) + 1:]

        time_at = next(
            (i for i, line in enumerate(rest) if re.fullmatch(r"\d{1,2}:\d{2}", line)), None
        )
        if time_at is None or len(rest) < time_at + 3:
            continue
        kickoff, home, away = rest[time_at], rest[time_at + 1], rest[time_at + 2]

        # Score cells run until the first non-numeric line (venue, or the next
        # card's Alpine blob).
        numbers = []
        for line in rest[time_at + 3:]:
            if re.fullmatch(r"\d{1,3}", line):
                numbers.append(int(line))
            else:
                break

        info = metadata.get(match_id, {})
        is_home = home.strip() == team_name.strip()
        opponent = away if is_home else home

        official_result, official_sets = "", ""
        if info.get("played") and len(numbers) >= 4 and len(numbers) % 2 == 0:
            sets_home, sets_away = numbers[-2], numbers[-1]
            pairs = [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 2, 2)]
            if is_home:
                official_result = f"{sets_home}-{sets_away}"
                official_sets = ", ".join(f"{h}-{a}" for h, a in pairs)
            else:
                official_result = f"{sets_away}-{sets_home}"
                official_sets = ", ".join(f"{a}-{h}" for h, a in pairs)

        fixtures.append({
            "profixio_match_id": match_id,
            "date": info.get("date", ""),
            "time": kickoff,
            "home": home,
            "away": away,
            "is_home": is_home,
            "opponent": opponent,
            "home_away": "home" if is_home else "away",
            "played": bool(info.get("played")),
            "official_result": official_result,
            "official_sets": official_sets,
        })

    fixtures.sort(key=lambda f: (f["date"], f["time"]))
    return fixtures


def parse_roster(html: str) -> list[dict]:
    """The squad list: shirt number and name."""
    start = html.find("lag-spillere-multi")
    if start == -1:
        return []
    lines = _lines(html[start:start + 60000])
    players = []
    seen = set()
    for index, line in enumerate(lines):
        found = re.fullmatch(r"#(\d{1,2})", line)
        if not found or index + 1 >= len(lines):
            continue
        number = int(found.group(1))
        name = lines[index + 1]
        if number in seen or not re.search(r"[A-Za-zÀ-ÿ]", name):
            continue
        seen.add(number)
        players.append({"number": number, "name": name})
    return sorted(players, key=lambda p: p["number"])


# --- the match protocol -----------------------------------------------------

def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover
        raise ProfixioError(f"pypdf is not installed ({exc})") from exc
    import io

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return " ".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ProfixioError(f"Could not read the protocol PDF: {exc}") from exc


def parse_protocol(text: str) -> dict:
    """Turn the Arbetsprotokoll into a header plus one dict per logged row."""
    flat = re.sub(r"\s+", " ", text).strip()

    home, away = _teams(flat)
    header = {
        "match_no": _first(r"Match nr:\s*(\d+)", flat),
        "series": _first(r"Serie:\s*(.+?)\s+Datum:", flat),
        "date": _first(r"Datum:\s*([\d-]+)", flat),
        "time": _first(r"Kl:\s*([\d:]+)", flat),
        "home": home,
        "away": away,
    }
    # The arena is whatever sits between "Arena:" and the fixture line. It has
    # commas but no dash, so it can only be bounded once the teams are known.
    header["arena"] = _first(
        r"Arena:\s*(.+?)\s*" + re.escape(home) + r"\s*-\s*" + re.escape(away), flat
    ) if home and away else ""

    rows = []
    anchors = list(re.finditer(r"(?<!\d)(\d{1,3})\s+(\d{2}:\d{2}:\d{2})\s", flat))
    for position, anchor in enumerate(anchors):
        end = anchors[position + 1].start() if position + 1 < len(anchors) else len(flat)
        body = flat[anchor.end():end].strip()
        # Page furniture repeats mid-document; strip it off the row it lands in.
        body = re.sub(r"\s*Sida \d+ av \d+.*$", "", body)
        body = re.sub(r"\s*Match nr:.*$", "", body)
        body = re.sub(r"\s*Powered by TCPDF.*$", "", body)
        rows.append(_parse_row(int(anchor.group(1)), anchor.group(2), body.strip(), header))
    return {**header, "rows": rows}


def _teams(flat: str) -> tuple[str, str]:
    """Work out the two team names.

    The away side is easy - it sits between the fixture dash and the table
    header. The home side cannot be read the same way because the arena runs
    straight into it with no separator, so it is recovered from the log itself:
    every logged row begins with a team name, and the two that recur are the
    teams.
    """
    away = _first(r"-\s+(.+?)\s+Rad\s+Tid", flat)
    keywords = "|".join(
        re.escape(word) for word in list(EVENT_MAP) + [OPPONENT_ERROR] + list(NON_SCORING)
    )
    counts = {}
    for found in re.finditer(
        r"\d{2}:\d{2}:\d{2}\s+(?:\d+\s*-\s*\d+\s+)?(.{2,40}?)\s+(?:" + keywords + r")", flat
    ):
        name = found.group(1).strip()
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts, key=lambda name: -counts[name])
    home = next((name for name in ranked if name != away), "")
    return home, away


def _first(pattern: str, text: str) -> str:
    found = re.search(pattern, text)
    return found.group(1).strip() if found else ""


def _parse_row(row_no: int, clock: str, body: str, header: dict) -> dict:
    row = {
        "row_no": row_no, "clock": clock, "raw": body,
        "score_home": None, "score_away": None,
        "team": "", "event": "", "number": None, "player": "",
        "set_start": None, "set_end": None, "match_end": False,
    }

    score = re.match(r"(\d+)\s*-\s*(\d+)\s*", body)
    if score:
        row["score_home"], row["score_away"] = int(score.group(1)), int(score.group(2))
        body = body[score.end():]

    for team in (header.get("home", ""), header.get("away", "")):
        if team and body.startswith(team):
            row["team"] = team
            body = body[len(team):].strip()
            break

    if MATCH_END in body:
        row["match_end"] = True
        return row
    set_end = SET_END.search(body)
    if set_end:
        row["set_end"] = int(set_end.group(1))
        return row
    set_start = SET_START.search(body)
    if set_start:
        row["set_start"] = int(set_start.group(1)) if set_start.group(1) else 1
        return row

    for keyword in list(EVENT_MAP) + [OPPONENT_ERROR] + list(NON_SCORING):
        if body.startswith(keyword):
            row["event"] = keyword
            tail = body[len(keyword):].strip()
            player = re.match(r"(\d{1,2})\s+(.+)", tail)
            if player:
                row["number"] = int(player.group(1))
                row["player"] = player.group(2).strip()
            break
    return row


def protocol_to_events(protocol: dict, team_name: str, match: dict, roster=None) -> list[dict]:
    """Map protocol rows onto our event schema.

    Only our own scoring actions become player events. Opponent errors and the
    opponent's points move the score but belong to nobody, so they are recorded
    as score movement only - exactly how the entry UI treats them.
    """
    match_id = match.get("match_id", "")
    we_are_home = protocol.get("home", "").strip() == team_name.strip()
    by_number = {}
    if roster is not None and len(roster):
        for player in roster.to_dict("records"):
            by_number[int(player["number"])] = player

    events = []
    set_no, seq = 1, 0
    score_us = score_them = 0

    for row in protocol["rows"]:
        if row["set_start"]:
            set_no, seq = row["set_start"], 0
            score_us = score_them = 0
            continue
        if row["set_end"] or row["match_end"]:
            continue   # the score on these rows is the set tally, not points

        if row["score_home"] is not None:
            score_us = row["score_away"] if not we_are_home else row["score_home"]
            score_them = row["score_home"] if not we_are_home else row["score_away"]

        mapped = EVENT_MAP.get(row["event"])
        if not mapped or row["team"].strip() != team_name.strip() or row["number"] is None:
            continue

        action, result = mapped
        known = by_number.get(row["number"], {})
        seq += 1
        events.append({
            "match_id": match_id,
            "match_date": match.get("date", ""),
            "match_name": store.match_name(match),
            "set_no": set_no,
            "player_num": row["number"],
            "player_name": known.get("name") or row["player"],
            "player_role": "",
            "action": action,
            "action_result": result,
            "is_point": schema.is_point(action, result),
            "source": schema.SOURCE_PROFIXIO,
            "event_id": f"pfx-{protocol['match_no']}-{row['row_no']}",
            "seq": seq,
            "score_us": score_us,
            "score_them": score_them,
        })
    return events


def protocol_summary(protocol: dict, team_name: str) -> dict:
    """Points for and against, reconstructed from the log, for a sanity check."""
    we_are_home = protocol.get("home", "").strip() == team_name.strip()
    ours = theirs = 0
    sets_us = sets_them = 0
    for row in protocol["rows"]:
        if row["set_end"] or row["match_end"]:
            if row["score_home"] is not None:
                sets_us = row["score_away"] if not we_are_home else row["score_home"]
                sets_them = row["score_home"] if not we_are_home else row["score_away"]
            continue
        if row["set_start"] or not row["event"]:
            continue
        if row["event"] in NON_SCORING:
            continue
        if row["team"].strip() == team_name.strip():
            ours += 1
        elif row["team"]:
            theirs += 1
    return {
        "points_for": ours, "points_against": theirs,
        "sets_for": sets_us, "sets_against": sets_them,
        "result": f"{sets_us}-{sets_them}",
        "rows": len(protocol["rows"]),
    }
