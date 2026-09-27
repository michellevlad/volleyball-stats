"""The adapter writes into tabs that already exist, so it must never disturb them."""

import pandas as pd
import pytest

from volley import schema, sheets

gspread = pytest.importorskip("gspread")
from gspread.utils import a1_to_rowcol  # noqa: E402


class FakeWorksheet:
    """Enough of a gspread worksheet to exercise the header-driven writers."""

    def __init__(self, title, values):
        self.title = title
        self.values = [list(row) for row in values]
        self.col_count = max((len(row) for row in self.values), default=0)
        self.cleared = False

    def row_values(self, index):
        return list(self.values[index - 1]) if len(self.values) >= index else []

    def get_all_values(self):
        return [list(row) for row in self.values]

    def update(self, values=None, range_name=None):
        row, col = a1_to_rowcol(str(range_name).split(":")[0])
        for row_offset, incoming in enumerate(values):
            target = row + row_offset - 1
            while len(self.values) <= target:
                self.values.append([])
            line = self.values[target]
            while len(line) < col - 1 + len(incoming):
                line.append("")
            for col_offset, cell in enumerate(incoming):
                line[col - 1 + col_offset] = cell

    def append_rows(self, rows, **kwargs):
        self.values.extend([list(row) for row in rows])

    def resize(self, rows=None, cols=None):
        if cols:
            self.col_count = cols

    def clear(self):
        self.values = []
        self.cleared = True


class FakeSpreadsheet:
    def __init__(self, tabs):
        self.title = "Elden VBK"
        self.tabs = {title: FakeWorksheet(title, values) for title, values in tabs.items()}

    def worksheets(self):
        return list(self.tabs.values())

    def worksheet(self, title):
        if title not in self.tabs:
            raise KeyError(title)
        return self.tabs[title]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWorksheet(title, [])
        return self.tabs[title]


# A tab that predates this app: its own column names, its own order, its own data.
EXISTING = [
    ["Fecha", "Jugadora", "Accion", "Resultado", "Comentario"],
    ["2026-01-10", "Ana", "remate", "punto", "buen pase"],
    ["2026-01-10", "Bea", "saque", "fallo", ""],
]


def test_ensure_columns_appends_at_the_far_right_and_keeps_order():
    worksheet = FakeWorksheet("Eventos", EXISTING)
    headers = sheets.ensure_columns(worksheet, ["Fecha", "action", "result", "event_id"])
    assert headers[:5] == ["Fecha", "Jugadora", "Accion", "Resultado", "Comentario"]
    assert headers[5:] == ["action", "result", "event_id"]
    assert worksheet.values[0] == headers


def test_ensure_columns_leaves_existing_data_untouched():
    worksheet = FakeWorksheet("Eventos", EXISTING)
    sheets.ensure_columns(worksheet, ["event_id", "video_seconds"])
    assert worksheet.values[1] == ["2026-01-10", "Ana", "remate", "punto", "buen pase"]
    assert worksheet.values[2] == ["2026-01-10", "Bea", "saque", "fallo", ""]
    assert not worksheet.cleared


def test_ensure_columns_is_a_noop_when_nothing_is_missing():
    worksheet = FakeWorksheet("Eventos", EXISTING)
    before = [list(row) for row in worksheet.values]
    assert sheets.ensure_columns(worksheet, ["Fecha", "Jugadora"]) == EXISTING[0]
    assert worksheet.values == before


def test_ensure_columns_on_an_empty_tab_writes_the_full_header():
    worksheet = FakeWorksheet("New", [])
    headers = sheets.ensure_columns(worksheet, ["a", "b"])
    assert headers == ["a", "b"] and worksheet.values[0] == ["a", "b"]


def test_append_mapped_positions_values_by_header_name():
    worksheet = FakeWorksheet("Eventos", EXISTING)
    frame = pd.DataFrame([
        {"event_id": "e1", "player_name": "Cyd", "action": "ATTACK",
         "action_result": "kill", "Comentario": "from the pipe"},
    ])
    written = sheets.append_mapped(
        worksheet, frame,
        ["event_id", "player_name", "action", "action_result", "Comentario"]
    )
    assert written == 1
    headers = worksheet.values[0]
    row = dict(zip(headers, worksheet.values[-1]))
    assert row["action"] == "ATTACK"
    assert row["Comentario"] == "from the pipe"
    # Columns the app knows nothing about are left blank, never overwritten.
    assert row["Jugadora"] == ""
    assert row["Fecha"] == ""


def test_append_mapped_appends_rather_than_replacing():
    worksheet = FakeWorksheet("Eventos", EXISTING)
    sheets.append_mapped(worksheet, pd.DataFrame([{"event_id": "e1"}]), ["event_id"])
    assert len(worksheet.values) == 4          # header + 2 existing + 1 new
    assert worksheet.values[1][1] == "Ana"     # the pre-existing rows survive


def test_append_mapped_with_nothing_to_write_touches_nothing():
    worksheet = FakeWorksheet("Eventos", EXISTING)
    assert sheets.append_mapped(worksheet, pd.DataFrame(), ["event_id"]) == 0
    assert len(worksheet.values) == 3


def test_read_tab_reduces_to_known_columns():
    spreadsheet = FakeSpreadsheet({"Eventos": EXISTING})
    frame = sheets.read_tab(spreadsheet, "Eventos", ["Fecha", "action"])
    assert list(frame.columns) == ["Fecha", "action"]
    assert list(frame["Fecha"]) == ["2026-01-10", "2026-01-10"]
    assert list(frame["action"]) == ["", ""]


def test_read_tab_of_a_missing_tab_is_empty_not_an_error():
    spreadsheet = FakeSpreadsheet({})
    assert len(sheets.read_tab(spreadsheet, "Nope", ["a"])) == 0


def test_suggest_mapping_prefers_an_exact_tab_name():
    spreadsheet = FakeSpreadsheet({
        "Roster": [schema.ROSTER_COLUMNS],
        "Matches": [schema.MATCH_COLUMNS],
        "Events": [schema.EVENT_COLUMNS],
    })
    assert sheets.suggest_mapping(spreadsheet) == {
        "roster": "Roster", "matches": "Matches", "events": "Events",
    }


def test_suggest_mapping_falls_back_to_header_overlap():
    spreadsheet = FakeSpreadsheet({
        "Partidos": [["match_id", "date", "opponent", "notes"]],
        "Acciones": [["event_id", "match_id", "action", "result", "player_id"]],
    })
    mapping = sheets.suggest_mapping(spreadsheet)
    assert mapping["matches"] == "Partidos"
    assert mapping["events"] == "Acciones"
    # Nothing resembles a roster, so it proposes creating one.
    assert mapping["roster"] == schema.TAB_ROSTER


def test_resolve_mapping_lets_a_saved_choice_win():
    spreadsheet = FakeSpreadsheet({"Events": [schema.EVENT_COLUMNS], "Otra": [["x"]]})
    mapping = sheets.resolve_mapping(spreadsheet, {"events": "Otra", "bogus": "ignored"})
    assert mapping["events"] == "Otra"
    assert "bogus" not in mapping


# --- push: one tab, rebuilt every time --------------------------------------

def make_events(n=2, match_id="m1", set_no=1):
    rows = []
    for index in range(n):
        rows.append({
            "match_id": match_id, "match_date": "2026-09-27",
            "match_name": "Elden VBK vs Lions", "set_no": set_no,
            "player_num": 7, "player_name": "Ana", "player_role": "OH",
            "action": schema.ATTACK, "action_result": "kill", "is_point": True,
            "source": schema.SOURCE_MANUAL, "event_id": f"e{set_no}-{index}",
            "seq": index + 1, "score_us": index + 1, "score_them": 0,
        })
    return pd.DataFrame(rows, columns=schema.EVENT_COLUMNS)


def make_matches(match_id="m1"):
    return pd.DataFrame([{
        "match_id": match_id, "date": "2026-09-27", "opponent": "Lions", "home_away": "home",
        "competition": "League", "sets_won": 0, "sets_lost": 0,
        "video_url": "", "profixio_match_id": "", "squad": "",
        "official_result": "", "official_sets": "", "notes": "",
    }], columns=schema.MATCH_COLUMNS)


@pytest.fixture
def spreadsheet():
    return FakeSpreadsheet({"Eventos": EXISTING})


def set_stats_rows(spreadsheet):
    tab = spreadsheet.worksheet(schema.TAB_SET_STATS)
    return [dict(zip(tab.values[0], row)) for row in tab.values[1:]]


def test_push_writes_only_the_per_set_table(spreadsheet):
    result = sheets.push(spreadsheet, make_events(2), make_matches())
    assert list(result["tabs"]) == [schema.TAB_SET_STATS]
    assert set(spreadsheet.tabs) == {"Eventos", schema.TAB_SET_STATS}


def test_the_per_set_table_has_the_expected_shape(spreadsheet):
    sheets.push(spreadsheet, make_events(3), make_matches())
    tab = spreadsheet.worksheet(schema.TAB_SET_STATS)
    assert tab.values[0] == schema.SET_STATS_COLUMNS
    assert "player_id" not in tab.values[0]

    rows = set_stats_rows(spreadsheet)
    assert len(rows) == 1                      # one player, one set
    assert rows[0]["player_num"] == 7
    assert rows[0]["player_name"] == "Ana"
    assert rows[0]["player_role"] == "OH"
    assert rows[0]["kills"] == 3
    # Rates are Looker's job.
    for rate in ("kill_pct", "hitting_eff", "pass_rating", "points"):
        assert rate not in tab.values[0]


def test_one_row_per_player_per_set(spreadsheet):
    events = pd.concat([make_events(2, set_no=1), make_events(3, set_no=2)],
                       ignore_index=True)
    sheets.push(spreadsheet, events, make_matches())
    rows = set_stats_rows(spreadsheet)
    assert sorted(r["set_no"] for r in rows) == [1, 2]
    assert {r["set_no"]: r["kills"] for r in rows} == {1: 2, 2: 3}


def test_pushing_twice_leaves_the_same_table(spreadsheet):
    """It is rebuilt, not appended, so there is nothing to deduplicate."""
    events, matches = make_events(3), make_matches()
    sheets.push(spreadsheet, events, matches)
    first = [list(row) for row in spreadsheet.worksheet(schema.TAB_SET_STATS).values]
    sheets.push(spreadsheet, events, matches)
    assert [list(row) for row in spreadsheet.worksheet(schema.TAB_SET_STATS).values] == first


def test_removing_an_event_removes_it_from_the_sheet(spreadsheet):
    """The aggregate follows the local data, including deletions."""
    sheets.push(spreadsheet, make_events(3), make_matches())
    assert set_stats_rows(spreadsheet)[0]["kills"] == 3
    sheets.push(spreadsheet, make_events(1), make_matches())
    assert set_stats_rows(spreadsheet)[0]["kills"] == 1


def test_other_tabs_are_untouched(spreadsheet):
    sheets.push(spreadsheet, make_events(2), make_matches())
    events_tab = spreadsheet.worksheet("Eventos")
    assert events_tab.values[1][:5] == ["2026-01-10", "Ana", "remate", "punto", "buen pase"]


def test_events_can_be_archived_as_well(spreadsheet, monkeypatch):
    """Opt in via VOLLEY_PUSH_TABS when the raw rows should leave this machine."""
    from volley import config

    monkeypatch.setattr(config, "push_tabs",
                        lambda: [schema.TAB_SET_STATS, schema.TAB_EVENTS])
    result = sheets.push(spreadsheet, make_events(2), make_matches())
    assert set(result["tabs"]) == {schema.TAB_SET_STATS, schema.TAB_EVENTS}
    assert result["tabs"][schema.TAB_EVENTS] == 2

    # ...and that one *is* deduplicated, because it appends.
    again = sheets.push(spreadsheet, make_events(2), make_matches())
    assert again["tabs"][schema.TAB_EVENTS] == 0


# --- auth failure messages --------------------------------------------------

def test_recognises_an_expired_token():
    assert sheets._is_reauth(Exception("Reauthentication is needed. Please run gcloud"))
    assert sheets._is_reauth(Exception("invalid_grant: Token has been expired"))
    assert not sheets._is_reauth(Exception("some other failure"))


def test_recognises_a_blocked_client():
    """Google now blocks the Sheets scope for gcloud's built-in client id."""
    assert sheets._is_blocked(Exception("Error 403: access_denied"))
    assert sheets._is_blocked(Exception("This app is blocked"))
    assert sheets._is_blocked(Exception("admin_policy_enforced"))
    assert not sheets._is_blocked(Exception("some other failure"))


def test_own_oauth_client_is_preferred_over_adc(monkeypatch, tmp_path):
    """A credentials.json on disk must win - ADC is the blocked path."""
    from volley import config

    monkeypatch.setattr(config, "service_account_path", lambda: tmp_path / "none.json")
    creds = tmp_path / "credentials.json"
    creds.write_text("{}")
    monkeypatch.setattr(sheets, "GSPREAD_CREDENTIALS", creds)
    monkeypatch.setattr(sheets.gspread, "oauth", lambda **kwargs: "oauth-client")

    def must_not_run(*args, **kwargs):
        raise AssertionError("ADC should not be reached when credentials.json exists")

    monkeypatch.setattr(sheets, "google_auth_default", must_not_run)
    assert sheets.get_client() == "oauth-client"


def test_blocked_adc_points_at_the_oauth_client(monkeypatch, tmp_path):
    from volley import config

    monkeypatch.setattr(config, "service_account_path", lambda: tmp_path / "none.json")
    monkeypatch.setattr(sheets, "GSPREAD_CREDENTIALS", tmp_path / "missing.json")

    def blocked(*args, **kwargs):
        raise Exception("Error 403: access_denied")

    monkeypatch.setattr(sheets, "google_auth_default", blocked)
    with pytest.raises(sheets.SheetsError, match="own OAuth client"):
        sheets.get_client()


def test_a_service_account_key_wins_over_everything(monkeypatch, tmp_path):
    """No browser, no consent screen - so it is tried first."""
    from volley import config

    key = tmp_path / "service_account.json"
    key.write_text("{}")
    monkeypatch.setattr(config, "service_account_path", lambda: key)
    monkeypatch.setattr(sheets.gspread, "service_account",
                        lambda filename, scopes: f"sa:{filename}")

    def must_not_run(*args, **kwargs):
        raise AssertionError("must not fall through to OAuth or ADC")

    monkeypatch.setattr(sheets.gspread, "oauth", must_not_run)
    monkeypatch.setattr(sheets, "google_auth_default", must_not_run)
    assert sheets.get_client() == f"sa:{key}"


def test_a_broken_service_account_key_is_reported_clearly(monkeypatch, tmp_path):
    from volley import config

    key = tmp_path / "service_account.json"
    key.write_text("not json")
    monkeypatch.setattr(config, "service_account_path", lambda: key)

    def boom(**kwargs):
        raise ValueError("bad key")

    monkeypatch.setattr(sheets.gspread, "service_account", boom)
    with pytest.raises(sheets.SheetsError, match="Service-account sign-in failed"):
        sheets.get_client()


def test_a_403_names_the_account_to_share_with(monkeypatch, tmp_path):
    """gspread raises a bare PermissionError with no message - the most likely
    failure and the least helpful one."""
    from volley import config

    key = tmp_path / "service_account.json"
    key.write_text('{"client_email": "bot@proj.iam.gserviceaccount.com"}')
    monkeypatch.setattr(config, "service_account_path", lambda: key)

    class Denied:
        def open_by_key(self, key):
            raise PermissionError

    with pytest.raises(sheets.SheetsError) as excinfo:
        sheets.open_spreadsheet(Denied(), "sheet-id")
    assert "bot@proj.iam.gserviceaccount.com" in str(excinfo.value)
    assert "Editor" in str(excinfo.value)


def test_a_missing_spreadsheet_says_so(monkeypatch, tmp_path):
    from volley import config

    monkeypatch.setattr(config, "service_account_path", lambda: tmp_path / "none.json")

    class Missing:
        def open_by_key(self, key):
            raise Exception("Requested entity was not found")

    with pytest.raises(sheets.SheetsError, match="VOLLEY_SPREADSHEET_ID"):
        sheets.open_spreadsheet(Missing(), "sheet-id")


# --- resuming a half-tracked match on another machine -----------------------

def test_events_can_be_read_back_out_of_the_sheet(spreadsheet, monkeypatch):
    from volley import config

    monkeypatch.setattr(config, "push_tabs",
                        lambda: [schema.TAB_SET_STATS, schema.TAB_EVENTS])
    sheets.push(spreadsheet, make_events(3), make_matches())

    back = sheets.read_events(spreadsheet)
    assert len(back) == 3
    assert list(back.columns) == schema.EVENT_COLUMNS
    # Types survive the round trip through the sheet's strings.
    assert back["set_no"].tolist() == [1, 1, 1]
    assert back["player_num"].tolist() == [7, 7, 7]
    assert bool(back["is_point"].iloc[0]) is True


def test_reading_back_without_the_archive_gives_nothing(spreadsheet):
    """Only PlayerSetStats was pushed - an aggregate cannot be reversed."""
    sheets.push(spreadsheet, make_events(3), make_matches())
    assert len(sheets.read_events(spreadsheet)) == 0


def test_restore_is_additive_and_never_overwrites_local_work(temp_store, monkeypatch):
    from volley import config, store

    spreadsheet = FakeSpreadsheet({})
    monkeypatch.setattr(config, "push_tabs",
                        lambda: [schema.TAB_SET_STATS, schema.TAB_EVENTS])

    # Three events pushed from the old machine.
    sheets.push(spreadsheet, make_events(3), make_matches())

    # A different machine has one of them plus some work of its own.
    local = make_events(1)
    own = make_events(1, set_no=2)
    for frame in (local, own):
        frame["synced"] = False
    store.save_events(pd.concat([local, own], ignore_index=True))

    result = store.restore_events(sheets.read_events(spreadsheet))
    assert result["added"] == 2
    assert result["already_here"] == 1

    after = store.load_events()
    assert len(after) == 4
    assert after["event_id"].duplicated().sum() == 0
    # The local-only event survived untouched.
    assert (after["event_id"] == own.iloc[0]["event_id"]).any()


def test_restoring_twice_adds_nothing(temp_store, monkeypatch):
    from volley import config, store

    spreadsheet = FakeSpreadsheet({})
    monkeypatch.setattr(config, "push_tabs",
                        lambda: [schema.TAB_SET_STATS, schema.TAB_EVENTS])
    sheets.push(spreadsheet, make_events(3), make_matches())

    store.restore_events(sheets.read_events(spreadsheet))
    second = store.restore_events(sheets.read_events(spreadsheet))
    assert second["added"] == 0
    assert len(store.load_events()) == 3


def test_a_restored_match_rebuilds_the_same_per_set_table(temp_store, monkeypatch):
    """The whole point: pick the match back up and the numbers are identical."""
    from volley import config, stats, store

    spreadsheet = FakeSpreadsheet({})
    monkeypatch.setattr(config, "push_tabs",
                        lambda: [schema.TAB_SET_STATS, schema.TAB_EVENTS])
    original = pd.concat([make_events(2, set_no=1), make_events(3, set_no=2)],
                         ignore_index=True)
    sheets.push(spreadsheet, original, make_matches())
    expected = stats.player_set_stats(original)

    store.restore_events(sheets.read_events(spreadsheet))
    restored = stats.player_set_stats(store.load_events())
    pd.testing.assert_frame_equal(
        expected.reset_index(drop=True), restored.reset_index(drop=True)
    )
