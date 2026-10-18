"""Google Sheets sync, authenticated as the signed-in user.

Primary auth path is Application Default Credentials from
`gcloud auth application-default login`, so there is no service-account key to
store or rotate - the app can only reach spreadsheets the user can already
reach. `gspread.oauth()` is the documented fallback for Workspace policies
that block ADC scopes.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, schema, stats, store

try:  # the app is fully usable offline, so Google libs are an optional import
    import gspread
    from gspread.utils import rowcol_to_a1
    from google.auth import default as google_auth_default
    from google.auth.exceptions import RefreshError

    GOOGLE_AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - depends on the environment
    GOOGLE_AVAILABLE = False
    IMPORT_ERROR = str(exc)
    RefreshError = Exception

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

GSPREAD_CREDENTIALS = Path.home() / ".config" / "gspread" / "credentials.json"

# gcloud requires cloud-platform alongside the rest, and rejects the whole
# flag if it is missing.
REAUTH_COMMAND = (
    "gcloud auth application-default login \\\n"
    "  --scopes=https://www.googleapis.com/auth/cloud-platform,"
    "https://www.googleapis.com/auth/spreadsheets,"
    "https://www.googleapis.com/auth/drive.file,"
    "openid,https://www.googleapis.com/auth/userinfo.email"
)
LOGIN_HINT = "Not signed in to Google. Run this, then reconnect:"
REAUTH_HINT = "Your Google sign-in has expired. Run this, then reconnect:"

# Google has started blocking the Sheets scope for gcloud's built-in client id
# ("Esta aplicación está bloqueada" / "This app is blocked"). When that happens
# the only way through is your own OAuth client.
BLOCKED_HINT = (
    "Google blocked gcloud's built-in client from using the Sheets scope. "
    "Create your own OAuth client instead - see 'When ADC stops working' in "
    f"README.md - and save it as {GSPREAD_CREDENTIALS}."
)


class SheetsError(RuntimeError):
    """Anything that stops us talking to the spreadsheet, with a readable message.

    `command` carries a shell one-liner that fixes it, so the UI can offer it
    as something to copy rather than burying it in prose.
    """

    def __init__(self, message: str, command: str = ""):
        super().__init__(message)
        self.command = command


def _is_blocked(exc: Exception) -> bool:
    """Google refusing the scope for gcloud's built-in client id."""
    text = str(exc).lower()
    return "blocked" in text or "access_denied" in text or "admin_policy_enforced" in text


def _is_reauth(exc: Exception) -> bool:
    """An expired ADC token. It surfaces on the first API call, not at sign-in."""
    if GOOGLE_AVAILABLE and isinstance(exc, RefreshError):
        return True
    text = str(exc).lower()
    return "reauthentication is needed" in text or "invalid_grant" in text


# --- auth -------------------------------------------------------------------

def get_client():
    """Service account, then your own OAuth client, then Application Default.

    The order matters: Google now blocks the Sheets scope for gcloud's built-in
    client id, so a credentials.json on disk is the more reliable path and is
    tried first. ADC can also *appear* to work and only fail at the first real
    API call, which is another reason not to prefer it.
    """
    if not GOOGLE_AVAILABLE:
        raise SheetsError(f"gspread / google-auth not installed ({IMPORT_ERROR})")

    # 1. A service-account key needs no browser and no consent screen.
    service_account = config.service_account_path()
    if service_account.exists():
        try:
            return gspread.service_account(filename=str(service_account), scopes=SCOPES)
        except Exception as exc:
            raise SheetsError(
                f"Service-account sign-in failed ({service_account.name}): {exc}"
            ) from exc

    # 2. Your own OAuth client - a browser window, once.
    if GSPREAD_CREDENTIALS.exists():
        try:
            return gspread.oauth(scopes=SCOPES)
        except Exception as oauth_error:
            raise SheetsError(
                f"Sign-in with your OAuth client failed: {oauth_error}"
            ) from oauth_error

    try:
        credentials, _ = google_auth_default(scopes=SCOPES)
        return gspread.authorize(credentials)
    except Exception as adc_error:
        if _is_blocked(adc_error):
            raise SheetsError(BLOCKED_HINT) from adc_error
        if _is_reauth(adc_error):
            raise SheetsError(REAUTH_HINT, REAUTH_COMMAND) from adc_error
        raise SheetsError(LOGIN_HINT, REAUTH_COMMAND) from adc_error


def account_identity() -> str:
    """Who the app is signing in as - the thing a sheet must be shared with."""
    path = config.service_account_path()
    if path.exists():
        try:
            import json
            return json.loads(path.read_text()).get("client_email", "")
        except Exception:
            return ""
    return ""


def _no_permission_hint(spreadsheet_id: str) -> str:
    identity = account_identity()
    if identity:
        return (
            "The spreadsheet exists but this app cannot open it. Share it with the "
            f"service account and give it Editor:\n\n{identity}\n\n"
            "In Google Sheets: Share \u2192 paste that address \u2192 Editor \u2192 Send "
            "(untick 'Notify people')."
        )
    return (
        f"Signed in, but not allowed to open spreadsheet {spreadsheet_id!r}. "
        "Check that the signed-in account has access to it."
    )


def open_spreadsheet(client, spreadsheet_id: str):
    try:
        return client.open_by_key(spreadsheet_id.strip())
    except Exception as exc:
        # The credentials look fine until the first real API call, which is
        # where an expired token actually shows up.
        if _is_blocked(exc):
            raise SheetsError(BLOCKED_HINT) from exc
        if _is_reauth(exc):
            raise SheetsError(REAUTH_HINT, REAUTH_COMMAND) from exc
        # gspread turns a 403 into a bare PermissionError with no message at
        # all, which is the single most likely failure and the least helpful.
        if isinstance(exc, PermissionError) or "permission" in str(exc).lower():
            raise SheetsError(_no_permission_hint(spreadsheet_id)) from exc
        if "not found" in str(exc).lower() or isinstance(exc, KeyError):
            raise SheetsError(
                f"No spreadsheet with id {spreadsheet_id!r}. Check VOLLEY_SPREADSHEET_ID in .env."
            ) from exc
        raise SheetsError(f"Could not open spreadsheet {spreadsheet_id!r}: {exc}") from exc


def account_email() -> str:
    """Best-effort label for the signed-in account, for the sidebar."""
    try:
        credentials, _ = google_auth_default(scopes=SCOPES)
        return getattr(credentials, "service_account_email", None) or getattr(
            credentials, "quota_project_id", ""
        ) or "signed in"
    except Exception:
        return "signed in"


# --- header-driven tab plumbing --------------------------------------------
# The spreadsheet already exists and its tabs have their own shape, so nothing
# here ever rewrites or reorders what is already in a tab. Columns are matched
# by header name; anything the app does not know about is left untouched.

def list_tab_titles(spreadsheet) -> list[str]:
    return [worksheet.title for worksheet in spreadsheet.worksheets()]


def read_headers(worksheet) -> list[str]:
    return [header for header in worksheet.row_values(1)]


def get_or_create(spreadsheet, title: str, headers: list[str]):
    """Fetch a tab, creating it with our headers only if it does not exist."""
    try:
        worksheet = spreadsheet.worksheet(title)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=title, rows=1000, cols=max(len(headers), 10)
        )
        worksheet.update(values=[headers], range_name="A1")
        return worksheet
    if not read_headers(worksheet):
        worksheet.update(values=[headers], range_name="A1")
    return worksheet


def ensure_columns(worksheet, needed: list[str]) -> list[str]:
    """Append any missing headers at the far right. Never reorders existing ones."""
    headers = read_headers(worksheet)
    if not headers:
        worksheet.update(values=[needed], range_name="A1")
        return list(needed)

    missing = [column for column in needed if column not in headers]
    if not missing:
        return headers

    first = len(headers) + 1
    last = len(headers) + len(missing)
    if worksheet.col_count < last:
        worksheet.resize(cols=last)
    span = f"{rowcol_to_a1(1, first)}:{rowcol_to_a1(1, last)}"
    worksheet.update(values=[missing], range_name=span)
    return headers + missing


def _cell(value):
    """Make a pandas/numpy value safe for the Sheets JSON payload."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return value


def append_mapped(worksheet, df: pd.DataFrame, needed: list[str]) -> int:
    """Append rows positioned by the tab's own header order."""
    if not len(df):
        return 0
    headers = ensure_columns(worksheet, needed)
    rows = [
        [_cell(record.get(header, "")) for header in headers]
        for record in df.to_dict("records")
    ]
    worksheet.append_rows(rows, value_input_option="USER_ENTERED", table_range="A1")
    return len(rows)


def read_tab_raw(spreadsheet, title: str) -> pd.DataFrame:
    """A tab exactly as it is, with its own headers."""
    try:
        worksheet = spreadsheet.worksheet(title)
    except Exception:
        return pd.DataFrame()
    values = worksheet.get_all_values()
    if len(values) < 2:
        return pd.DataFrame(columns=values[0] if values else [])
    return pd.DataFrame(values[1:], columns=values[0])


def read_tab(spreadsheet, title: str, columns: list[str]) -> pd.DataFrame:
    """A tab reduced to the columns the app understands."""
    frame = read_tab_raw(spreadsheet, title)
    if not len(frame):
        return pd.DataFrame(columns=columns)
    return frame.reindex(columns=columns).fillna("")


def replace_tab(spreadsheet, title: str, df: pd.DataFrame, columns: list[str]) -> None:
    """Overwrite a whole tab. Only ever used for the app-owned aggregate tabs."""
    worksheet = get_or_create(spreadsheet, title, columns)
    rows = [[_cell(value) for value in row] for row in df.reindex(columns=columns).itertuples(index=False)]
    worksheet.resize(rows=max(len(rows) + 1, 2), cols=max(len(columns), 1))
    worksheet.clear()
    worksheet.update(values=[columns] + rows, range_name="A1")


# --- tab mapping ------------------------------------------------------------

def suggest_mapping(spreadsheet) -> dict:
    """Guess which existing tab plays each role: exact name, then header overlap."""
    titles = list_tab_titles(spreadsheet)
    lowered = {title.lower(): title for title in titles}
    mapping = {}
    for role, default_title in schema.MAPPABLE_ROLES.items():
        exact = lowered.get(default_title.lower())
        if exact:
            mapping[role] = exact
            continue
        wanted = {column.lower() for column in schema.ROLE_COLUMNS[role]}
        best, best_score = None, 0
        for title in titles:
            try:
                headers = {h.strip().lower() for h in read_headers(spreadsheet.worksheet(title))}
            except Exception:
                continue
            score = len(headers & wanted)
            if score > best_score:
                best, best_score = title, score
        # Two shared column names is weak evidence; below that, make a new tab.
        mapping[role] = best if best_score >= 2 else default_title
    return mapping


def resolve_mapping(spreadsheet, saved: dict | None = None) -> dict:
    mapping = dict(suggest_mapping(spreadsheet))
    for role, title in (saved or {}).items():
        if role in schema.MAPPABLE_ROLES and title:
            mapping[role] = title
    return mapping


# --- the pieces the app calls ----------------------------------------------

def ensure_tabs(spreadsheet, mapping: dict | None = None) -> list[str]:
    """Create the tabs a push will write, plus any mapped ones it reads."""
    created = []
    existing = set(list_tab_titles(spreadsheet))
    wanted = {title: schema.TAB_HEADERS[title] for title in config.push_tabs()
              if title in schema.TAB_HEADERS}
    for role, title in (mapping or {}).items():
        if role in schema.ROLE_COLUMNS:
            wanted[title] = schema.ROLE_COLUMNS[role]
    for title, columns in wanted.items():
        if title not in existing:
            created.append(title)
        get_or_create(spreadsheet, title, columns)
    return created


def read_roster(spreadsheet, title: str) -> pd.DataFrame:
    roster = read_tab(spreadsheet, title, schema.ROSTER_COLUMNS)
    if len(roster):
        roster["number"] = pd.to_numeric(roster["number"], errors="coerce").fillna(0).astype(int)
        roster["active"] = ~roster["active"].astype(str).str.strip().str.lower().isin(
            {"false", "0", "no", "n"}
        )
    return roster


def write_roster(spreadsheet, title: str, roster: pd.DataFrame) -> None:
    """The roster is small and app-managed, so it is safe to rewrite wholesale."""
    replace_tab(spreadsheet, title, roster, schema.ROSTER_COLUMNS)


def _merge_lineup(spreadsheet, lineup: pd.DataFrame) -> pd.DataFrame:
    """Local lineup wins per (match, set, player); rows only in the sheet stay.

    The lineup is authored here rather than derived, so it is merged rather
    than overwritten - otherwise clearing the local buffer would lose it.
    """
    remote = read_tab(spreadsheet, schema.TAB_LINEUP, schema.LINEUP_COLUMNS)
    merged = store.concat_frames([lineup, remote])
    if not len(merged):
        return merged
    for column in ("set_no", "player_num"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0).astype(int)
    return merged.drop_duplicates(["match_id", "set_no", "player_num"], keep="first")


NUMERIC_STAT_COLUMNS = ("set_no", "player_num", "sets_played")


def upsert_by_match(spreadsheet, title: str, df: pd.DataFrame, columns: list[str]) -> int:
    """Replace the rows for the matches we hold; leave every other match alone.

    An aggregate row is a summary, not a fact - it changes as you enter more -
    so it has to be rewritten rather than appended. But rewriting the *whole*
    tab makes it a mirror of this one machine: lose the local buffer, push, and
    the sheet empties with it. Scoping the rewrite to the matches present
    locally keeps corrections and deletions working inside a match while a
    match this machine has never seen simply stays where it is.
    """
    remote = read_tab(spreadsheet, title, columns)
    ours = set(df["match_id"]) if len(df) else set()
    kept = remote[~remote["match_id"].isin(ours)] if len(remote) else remote

    merged = store.concat_frames([kept, df]).reindex(columns=columns)
    if len(merged):
        for column in NUMERIC_STAT_COLUMNS:
            if column in merged.columns:
                merged[column] = (
                    pd.to_numeric(merged[column], errors="coerce").fillna(0).astype(int)
                )
        sort_by = [c for c in ("match_date", "match_id", "set_no", "player_num")
                   if c in merged.columns]
        merged = merged.sort_values(sort_by)

    replace_tab(spreadsheet, title, merged, columns)
    return len(merged)


def mirror_rows_by_id(worksheet, df: pd.DataFrame, columns: list[str],
                      scope_column: str = "match_id",
                      id_column: str = "event_id") -> dict:
    """Make the sheet match this machine, for the matches this machine holds.

    One rule, the same as the per-set table: **a match you hold locally is
    mirrored; a match you do not hold is left exactly as it is.**

    That means corrections reach rows written months ago, and events you delete
    stop coming back - without which Restore from Sheets would resurrect
    everything Review duplicates had just removed. A match this machine has
    never seen is untouched, which is what makes the archive worth keeping.

    Columns the app does not know about are carried across untouched.
    """
    headers = ensure_columns(worksheet, columns)
    existing = worksheet.get_all_values()
    if len(existing) < 1:
        return {"added": append_mapped(worksheet, df, columns), "updated": 0, "removed": 0}

    id_at, scope_at = headers.index(id_column), headers.index(scope_column)

    def cell(row, index):
        return row[index] if index < len(row) else ""

    local_by_id = {str(r.get(id_column, "")): r for r in df.to_dict("records")}
    local_scopes = set(df[scope_column].astype(str)) if len(df) else set()

    kept, updated, removed, seen = [], 0, 0, set()
    for row in existing[1:]:
        key = cell(row, id_at)
        if not key and not any(c.strip() for c in row):
            continue
        record = local_by_id.get(key)
        if record is None:
            # Only drop it if this machine owns that match; otherwise it is
            # someone else's work, or a match we simply do not have.
            if cell(row, scope_at) in local_scopes:
                removed += 1
                continue
            kept.append([cell(row, i) for i in range(len(headers))])
            continue
        seen.add(key)
        merged = [
            _cell(record.get(header, "")) if header in columns else cell(row, index)
            for index, header in enumerate(headers)
        ]
        if [str(v) for v in merged] != [str(cell(row, i)) for i in range(len(headers))]:
            updated += 1
        kept.append(merged)

    fresh = [record for key, record in local_by_id.items() if key not in seen]
    for record in fresh:
        kept.append([_cell(record.get(header, "")) for header in headers])

    worksheet.resize(rows=max(len(kept) + 1, 2), cols=max(len(headers), 1))
    worksheet.clear()
    worksheet.update(values=[headers] + kept, range_name="A1")
    return {"added": len(fresh), "updated": updated, "removed": removed}


def read_events(spreadsheet, title: str | None = None) -> pd.DataFrame:
    """Read the archived raw events back out of the spreadsheet.

    Only possible when `Events` is in VOLLEY_PUSH_TABS. The per-set table is an
    aggregate and cannot be turned back into the actions it was built from, so
    without the archive there is nothing to restore.
    """
    frame = read_tab(spreadsheet, title or schema.TAB_EVENTS, schema.EVENT_COLUMNS)
    if not len(frame):
        return frame
    for column in ("set_no", "seq", "player_num", "score_us", "score_them"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype(int)
    frame["is_point"] = frame["is_point"].astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes"}
    )
    return frame


def push(spreadsheet, events: pd.DataFrame, matches: pd.DataFrame,
         mapping: dict | None = None, lineup: pd.DataFrame | None = None) -> dict:
    """Publish the tabs listed in VOLLEY_PUSH_TABS.

    By default that is `PlayerSetStats` alone: one row per player per set, all
    counts, rebuilt from the local events every time. Because it is rewritten
    wholesale there is nothing to deduplicate and pushing twice is the same as
    pushing once.

    Adding `Events` to the list also archives the raw rows. That matters if you
    want a copy of them anywhere other than this machine - the aggregate cannot
    be taken apart again.
    """
    wanted = config.push_tabs()
    mapping = mapping or {}
    written = {}
    corrected = removed = 0

    for column in ("set_no", "seq", "player_num", "score_us", "score_them"):
        if column in events.columns:
            events[column] = (
                pd.to_numeric(events[column], errors="coerce").fillna(0).astype(int)
            )

    if schema.TAB_SET_STATS in wanted:
        written[schema.TAB_SET_STATS] = upsert_by_match(
            spreadsheet, schema.TAB_SET_STATS,
            stats.player_set_stats(events), schema.SET_STATS_COLUMNS,
        )

    # The rest are opt-in, and behave as they always did.
    if schema.TAB_EVENTS in wanted:
        title = mapping.get("events", schema.TAB_EVENTS)
        get_or_create(spreadsheet, title, schema.EVENT_COLUMNS)
        outcome = mirror_rows_by_id(
            spreadsheet.worksheet(title), events, schema.EVENT_COLUMNS
        )
        written[schema.TAB_EVENTS] = outcome["added"] + outcome["updated"]
        corrected, removed = outcome["updated"], outcome["removed"]

    if schema.TAB_MATCHES in wanted:
        title = mapping.get("matches", schema.TAB_MATCHES)
        get_or_create(spreadsheet, title, schema.MATCH_COLUMNS)
        remote = read_tab(spreadsheet, title, schema.MATCH_COLUMNS)
        known = set(remote["match_id"]) if len(remote) else set()
        fresh = matches[~matches["match_id"].isin(known)]
        written[schema.TAB_MATCHES] = append_mapped(
            spreadsheet.worksheet(title), fresh, schema.MATCH_COLUMNS
        )

    if schema.TAB_LINEUP in wanted and lineup is not None:
        replace_tab(spreadsheet, schema.TAB_LINEUP,
                    _merge_lineup(spreadsheet, lineup), schema.LINEUP_COLUMNS)
        written[schema.TAB_LINEUP] = len(lineup)

    for title, columns, frame in (
        (schema.TAB_PLAYER_STATS, schema.PLAYER_STATS_COLUMNS,
         lambda: stats.player_match_stats(events)),
        (schema.TAB_TEAM_STATS, schema.TEAM_STATS_COLUMNS,
         lambda: stats.team_match_stats(events)),
        (schema.TAB_ROLE_STATS, schema.ROLE_STATS_COLUMNS,
         lambda: stats.player_role_stats(events)),
    ):
        if title in wanted:
            built = frame()
            replace_tab(spreadsheet, title, built, columns)
            written[title] = len(built)

    return {
        "tabs": written,
        "corrected": corrected,
        "removed": removed,
        "rows": sum(written.values()),
        "events_total": len(events),
        "pushed_ids": list(events["event_id"]) if "event_id" in events.columns else [],
    }
