"""Google Sheets backend helpers for the tutor hours tracker.

All reads/writes go through a single worksheet whose columns are defined in
``COLUMNS``. Credentials are read from ``st.secrets`` so the app works both
locally (``.streamlit/secrets.toml``) and on Streamlit Community Cloud.
"""

from __future__ import annotations

from datetime import date, datetime, time

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# Google API scopes required to read/write Sheets and open by name via Drive.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# The one and only source of truth for column order / headers.
COLUMNS = [
    "id",
    "date",
    "start_time",
    "end_time",
    "duration_hours",
    "extra_minutes",
    "participants",
    "notes",
]

# Fixed set of who a session can involve (single-student use case).
PARTICIPANT_OPTIONS = ["Student", "Nico", "Company", "Just me (prep/reports)"]


# --------------------------------------------------------------------------- #
# Connection
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def _get_worksheet():
    """Authorize with the service account and return the target worksheet.

    Cached as a resource so we authorize once per session rather than on every
    interaction. Expects the following in ``st.secrets``::

        [gcp_service_account]
        # ... the full service-account JSON key, field by field ...

        [sheet]
        spreadsheet = "<spreadsheet key, full URL, or exact title>"
        worksheet   = "Sessions"   # optional, defaults to "Sessions"
    """
    sa_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client = gspread.authorize(creds)

    sheet_cfg = st.secrets["sheet"]
    spreadsheet_ref = sheet_cfg["spreadsheet"]
    worksheet_name = sheet_cfg.get("worksheet", "Sessions")

    spreadsheet = _open_spreadsheet(client, spreadsheet_ref)

    try:
        ws = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=worksheet_name, rows=100, cols=len(COLUMNS))

    _ensure_headers(ws)
    return ws


def _open_spreadsheet(client: gspread.Client, ref: str):
    """Open a spreadsheet by key, URL, or title — whichever the ref looks like."""
    if ref.startswith("http"):
        return client.open_by_url(ref)
    # A raw key is a long token without spaces; titles usually have spaces.
    try:
        return client.open_by_key(ref)
    except Exception:
        return client.open(ref)


def _ensure_headers(ws) -> None:
    """Write the header row if the sheet is brand new / empty."""
    first_row = ws.row_values(1)
    if first_row != COLUMNS:
        if not first_row:
            ws.update(range_name="A1", values=[COLUMNS], value_input_option="RAW")
        # If a header row exists but differs, we leave it alone rather than
        # clobber the user's data; the README documents the expected headers.


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=300, show_spinner="Loading sessions…")
def read_sessions() -> pd.DataFrame:
    """Return all sessions as a DataFrame with the canonical columns.

    Cached so we don't hit the Sheets API on every rerun. Call
    :func:`refresh` after any write to invalidate the cache.
    """
    ws = _get_worksheet()
    records = ws.get_all_records(expected_headers=COLUMNS)
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(records)
    # Guarantee every expected column exists and ordering is stable.
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def refresh() -> None:
    """Invalidate the cached sheet read so the next load re-fetches."""
    read_sessions.clear()


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #
def _next_id(ws) -> int:
    """Return max existing integer id + 1 (starts at 1 on an empty sheet)."""
    id_values = ws.col_values(1)[1:]  # skip header
    max_id = 0
    for val in id_values:
        try:
            max_id = max(max_id, int(val))
        except (ValueError, TypeError):
            continue
    return max_id + 1


def _row_number_for_id(ws, session_id) -> int | None:
    """Return the 1-based sheet row for the given id, or None if not found."""
    id_values = ws.col_values(1)  # includes header at index 0
    target = str(session_id)
    for idx, val in enumerate(id_values):
        if str(val) == target:
            return idx + 1
    return None


def add_session(
    session_date: date,
    start_time: time,
    end_time: time,
    duration_hours: float,
    extra_minutes: int,
    participants: str,
    notes: str,
) -> None:
    """Append a new session row and return nothing (caller refreshes)."""
    ws = _get_worksheet()
    new_id = _next_id(ws)
    row = _to_row(
        new_id, session_date, start_time, end_time,
        duration_hours, extra_minutes, participants, notes,
    )
    ws.append_row(row, value_input_option="RAW")


def update_session(
    session_id,
    session_date: date,
    start_time: time,
    end_time: time,
    duration_hours: float,
    extra_minutes: int,
    participants: str,
    notes: str,
) -> bool:
    """Overwrite the row with the given id. Returns True if the row was found."""
    ws = _get_worksheet()
    row_number = _row_number_for_id(ws, session_id)
    if row_number is None:
        return False
    row = _to_row(
        session_id, session_date, start_time, end_time,
        duration_hours, extra_minutes, participants, notes,
    )
    last_col = chr(ord("A") + len(COLUMNS) - 1)  # "H" for 8 columns
    ws.update(
        range_name=f"A{row_number}:{last_col}{row_number}",
        values=[row],
        value_input_option="RAW",
    )
    return True


def delete_session(session_id) -> bool:
    """Delete the row with the given id. Returns True if the row was found."""
    ws = _get_worksheet()
    row_number = _row_number_for_id(ws, session_id)
    if row_number is None:
        return False
    ws.delete_rows(row_number)
    return True


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _to_row(session_id, session_date, start_time, end_time,
            duration_hours, extra_minutes, participants, notes) -> list:
    """Serialize a session into the ordered list of cell values."""
    return [
        session_id,
        session_date.isoformat(),
        start_time.strftime("%H:%M"),
        end_time.strftime("%H:%M"),
        duration_hours,
        extra_minutes,
        participants,
        notes,
    ]


def parse_participants(value) -> list:
    """Split a stored 'A, B' participants string into a list of known options.

    Values not in PARTICIPANT_OPTIONS are dropped so the result is always a
    valid default for st.multiselect.
    """
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    return [p for p in parts if p in PARTICIPANT_OPTIONS]


def parse_time(value) -> time:
    """Parse a stored time string ('HH:MM' or 'HH:MM:SS') into a time object."""
    text = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return time(0, 0)


def parse_date(value) -> date:
    """Parse a stored ISO date string into a date object (falls back to today)."""
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def compute_duration_hours(start_time: time, end_time: time) -> float:
    """Hours between two same-day times, rounded to 2 dp.

    Returns a negative number if end precedes start; the UI validates against
    that so a negative duration is never silently written.
    """
    anchor = date.today()
    delta = datetime.combine(anchor, end_time) - datetime.combine(anchor, start_time)
    return round(delta.total_seconds() / 3600, 2)
