"""Tutor hours tracker — a minimal Streamlit app.

The tutor is paid a flat monthly fee for a set number of contracted hours but
often works more. This app logs each session, computes real hours worked, and
compares them against the contracted amount so the gap is visible for future
rate negotiations.

Backend: a single Google Sheet worksheet (see sheets.py).
"""

from __future__ import annotations

from datetime import date, time

import pandas as pd
import streamlit as st

import sheets

st.set_page_config(page_title="Tutor Hours Tracker", page_icon="⏱️", layout="centered")
st.title("⏱️ Tutor Hours Tracker")


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_data() -> pd.DataFrame:
    """Load sessions and add parsed/derived columns used across the tabs."""
    df = sheets.read_sessions()
    if df.empty:
        return df
    df = df.copy()
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
    df["duration_hours"] = pd.to_numeric(df["duration_hours"], errors="coerce").fillna(0.0)
    df["month"] = df["date_parsed"].dt.to_period("M")
    return df


try:
    data = load_data()
except KeyError as exc:
    st.error(
        "Missing configuration in Streamlit secrets: "
        f"`{exc.args[0]}`.\n\nSee the README for how to set up "
        "`.streamlit/secrets.toml` (locally) or the Community Cloud secrets manager."
    )
    st.stop()
except Exception as exc:  # noqa: BLE001 — surface any connection error cleanly.
    st.error(f"Could not connect to Google Sheets:\n\n`{exc}`")
    st.info(
        "Check that the spreadsheet reference in secrets is correct and that the "
        "sheet is shared (Editor access) with the service account's email address."
    )
    st.stop()


log_tab, manage_tab, summary_tab, history_tab = st.tabs(
    ["➕ Log session", "✏️ Edit / delete", "📊 Monthly summary", "📈 History"]
)


# --------------------------------------------------------------------------- #
# 1. Log a session
# --------------------------------------------------------------------------- #
with log_tab:
    st.subheader("Log a session")
    with st.form("add_session", clear_on_submit=True):
        session_date = st.date_input("Date", value=date.today(), format="DD/MM/YYYY")
        col1, col2 = st.columns(2)
        start_time = col1.time_input("Start time", value=time(9, 0), step=300)
        end_time = col2.time_input("End time", value=time(10, 0), step=300)
        participants = st.multiselect(
            "Who was this session with?", sheets.PARTICIPANT_OPTIONS,
            help="Tick everyone the session involved.",
        )
        subject = st.text_input("Subject")
        notes = st.text_area("Notes", placeholder="Optional")
        submitted = st.form_submit_button("Add session", type="primary")

    if submitted:
        duration = sheets.compute_duration_hours(start_time, end_time)
        if duration <= 0:
            st.error("End time must be after start time.")
        elif not participants:
            st.error("Pick at least one person under “Who was this session with?”.")
        else:
            sheets.add_session(
                session_date, start_time, end_time, duration,
                ", ".join(participants), subject.strip(), notes.strip(),
            )
            sheets.refresh()
            st.success(f"Logged {duration:.2f} h on {session_date.strftime('%d/%m/%Y')}.")
            st.rerun()


# --------------------------------------------------------------------------- #
# 2. Edit / delete sessions
# --------------------------------------------------------------------------- #
with manage_tab:
    st.subheader("Edit or delete a session")

    if data.empty:
        st.info("No sessions logged yet. Add one in the **Log session** tab.")
    else:
        display = (
            data.sort_values("date_parsed", ascending=False)
            [["id", "date_parsed", "start_time", "end_time", "duration_hours",
              "participants", "subject", "notes"]]
            .reset_index(drop=True)
        )
        # Show the date as dd/mm/yyyy (falls back to the raw value if unparsed).
        display["date"] = display["date_parsed"].dt.strftime("%d/%m/%Y")
        display = display[["id", "date", "start_time", "end_time", "duration_hours",
                           "participants", "subject", "notes"]]
        st.dataframe(display, use_container_width=True, hide_index=True)

        # Build a friendly label -> id map for the selector.
        options = {}
        for _, r in display.iterrows():
            label = (
                f"#{r['id']} · {r['date']} {r['start_time']}–{r['end_time']} · "
                f"{r['participants'] or '—'} ({r['subject'] or '—'})"
            )
            options[label] = r["id"]

        selected_label = st.selectbox("Select a session", list(options.keys()))
        selected_id = options[selected_label]
        row = data[data["id"].astype(str) == str(selected_id)].iloc[0]

        with st.form("edit_session"):
            e_date = st.date_input(
                "Date", value=sheets.parse_date(row["date"]), format="DD/MM/YYYY"
            )
            c1, c2 = st.columns(2)
            e_start = c1.time_input(
                "Start time", value=sheets.parse_time(row["start_time"]), step=300
            )
            e_end = c2.time_input(
                "End time", value=sheets.parse_time(row["end_time"]), step=300
            )
            e_participants = st.multiselect(
                "Who was this session with?", sheets.PARTICIPANT_OPTIONS,
                default=sheets.parse_participants(row["participants"]),
            )
            e_subject = st.text_input("Subject", value=str(row["subject"]))
            e_notes = st.text_area("Notes", value=str(row["notes"]))

            save_col, del_col = st.columns(2)
            save = save_col.form_submit_button("Save changes", type="primary")
            delete = del_col.form_submit_button("Delete session")

        if save:
            duration = sheets.compute_duration_hours(e_start, e_end)
            if duration <= 0:
                st.error("End time must be after start time.")
            elif not e_participants:
                st.error("Pick at least one person under “Who was this session with?”.")
            else:
                sheets.update_session(
                    selected_id, e_date, e_start, e_end, duration,
                    ", ".join(e_participants), e_subject.strip(), e_notes.strip(),
                )
                sheets.refresh()
                st.success("Session updated.")
                st.rerun()

        if delete:
            sheets.delete_session(selected_id)
            sheets.refresh()
            st.success(f"Deleted session #{selected_id}.")
            st.rerun()


# --------------------------------------------------------------------------- #
# 3. Monthly summary
# --------------------------------------------------------------------------- #
with summary_tab:
    st.subheader("Monthly summary")

    today = date.today()
    current_period = pd.Period(today, freq="M")

    # Offer months that have data, plus the current month, newest first.
    periods = set()
    if not data.empty:
        periods = set(data["month"].dropna().unique())
    periods.add(current_period)
    period_list = sorted(periods, reverse=True)

    labels = {p.strftime("%B %Y"): p for p in period_list}
    default_label = current_period.strftime("%B %Y")
    chosen_label = st.selectbox(
        "Month", list(labels.keys()),
        index=list(labels.keys()).index(default_label),
    )
    chosen_period = labels[chosen_label]

    contracted = st.number_input(
        "Contracted hours this month",
        min_value=0.0, value=20.0, step=1.0,
        help="The flat number of hours the monthly fee covers.",
    )

    if data.empty:
        month_hours = 0.0
    else:
        month_hours = float(
            data.loc[data["month"] == chosen_period, "duration_hours"].sum()
        )

    difference = month_hours - contracted

    m1, m2, m3 = st.columns(3)
    m1.metric("Hours logged", f"{month_hours:.2f}")
    m2.metric("Contracted", f"{contracted:.2f}")
    m3.metric(
        "Difference",
        f"{difference:+.2f}",
        delta=f"{difference:+.2f} h",
        help="Positive = worked more than contracted.",
    )

    if difference > 0:
        st.warning(f"Worked **{difference:.2f} h over** the contracted amount.")
    elif difference < 0:
        st.info(f"Worked **{abs(difference):.2f} h under** the contracted amount.")
    else:
        st.success("Exactly on the contracted hours.")


# --------------------------------------------------------------------------- #
# 4. History view
# --------------------------------------------------------------------------- #
with history_tab:
    st.subheader("Hours per month")

    if data.empty:
        st.info("No sessions logged yet.")
    else:
        monthly = (
            data.dropna(subset=["month"])
            .groupby("month")["duration_hours"].sum()
            .sort_index()
        )
        monthly.index = monthly.index.astype(str)
        monthly.name = "Total hours"

        st.bar_chart(monthly)
        st.dataframe(
            monthly.reset_index().rename(columns={"month": "Month"}),
            use_container_width=True, hide_index=True,
        )
        st.caption(f"Total logged all-time: **{monthly.sum():.2f} h**")
