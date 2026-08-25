"""Tutor hours tracker — a minimal Streamlit app.

The tutor is paid a flat monthly fee for a set number of contracted hours but
often works more. This app logs each session, computes real hours worked, and
compares them against the contracted amount so the gap is visible for future
rate negotiations.

Backend: a single Google Sheet worksheet (see sheets.py).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

import sheets

LOGO_PATH = str(Path(__file__).parent / "assets" / "logo.png")

# Quick-pick session lengths (label -> minutes); a "Custom…" option lets the
# user type any value instead.
LENGTH_PRESETS = {"10 min": 10, "20 min": 20, "30 min": 30, "45 min": 45, "1 hour": 60}


def pick_minutes(default: int, key_prefix: str) -> int:
    """Render quick-pick length options plus a custom minutes box; return minutes.

    If `default` matches a preset it's pre-selected; otherwise the picker starts
    on "Custom…" pre-filled with `default`.
    """
    labels = list(LENGTH_PRESETS.keys()) + ["Custom…"]
    if default in LENGTH_PRESETS.values():
        index = list(LENGTH_PRESETS.values()).index(default)
        custom_default = 0
    else:
        index = len(labels) - 1  # "Custom…"
        custom_default = int(default)

    choice = st.radio(
        "Session length", labels, index=index, horizontal=True,
        key=f"{key_prefix}_length",
    )
    custom = st.number_input(
        "Custom length (minutes)", min_value=0, value=custom_default, step=5,
        key=f"{key_prefix}_custom",
        help="Only used when “Custom…” is selected above.",
    )
    return int(custom) if choice == "Custom…" else LENGTH_PRESETS[choice]

st.set_page_config(
    page_title="Track your time! Please and thank you",
    page_icon=Image.open(LOGO_PATH),  # browser tab / bookmark icon
    layout="centered",
)
st.logo(LOGO_PATH)  # small logo in the top-left corner
st.markdown(
    "<h1 style='color:#16256C;'>Track your time! Please and thank you</h1>",
    unsafe_allow_html=True,
)


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
    df["duration_minutes"] = pd.to_numeric(df["duration_minutes"], errors="coerce").fillna(0.0)
    df["extra_minutes"] = pd.to_numeric(df["extra_minutes"], errors="coerce").fillna(0.0)
    # Total real time = the session length plus any extra independent minutes.
    df["total_hours"] = (df["duration_minutes"] + df["extra_minutes"]) / 60.0
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
    ["Log session", "Edit / delete", "Monthly summary", "History"]
)


# --------------------------------------------------------------------------- #
# 1. Log a session
# --------------------------------------------------------------------------- #
with log_tab:
    st.subheader("Log a session")
    with st.form("add_session", clear_on_submit=True):
        session_date = st.date_input("Date", value=date.today(), format="DD/MM/YYYY")
        duration_minutes = pick_minutes(default=30, key_prefix="log")
        participants = st.multiselect(
            "Who was this session with?", sheets.PARTICIPANT_OPTIONS,
            help="Tick everyone the session involved.",
        )
        extra_minutes = st.number_input(
            "Do you want to log additional independent time for this session "
            "(prep, review, reports)?",
            min_value=0, value=0, step=5,
            help="In minutes. Leave at 0 if none. This is added on top of the "
                 "session length above.",
        )
        notes = st.text_area("Notes", placeholder="Optional")
        submitted = st.form_submit_button("Add session", type="primary")

    if submitted:
        if duration_minutes <= 0:
            st.error("Enter a session length greater than 0 minutes.")
        elif not participants:
            st.error("Pick at least one person under “Who was this session with?”.")
        else:
            sheets.add_session(
                session_date, int(duration_minutes), int(extra_minutes),
                ", ".join(participants), notes.strip(),
            )
            sheets.refresh()
            total = (int(duration_minutes) + int(extra_minutes)) / 60.0
            st.success(
                f"Logged {total:.2f} h on {session_date.strftime('%d/%m/%Y')} "
                f"({int(duration_minutes)} min session + {int(extra_minutes)} min extra)."
            )
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
            [["id", "date_parsed", "duration_minutes",
              "extra_minutes", "participants", "notes"]]
            .reset_index(drop=True)
        )
        # Show the date as dd/mm/yyyy (falls back to the raw value if unparsed).
        display["date"] = display["date_parsed"].dt.strftime("%d/%m/%Y")
        display = display[["id", "date", "duration_minutes",
                           "extra_minutes", "participants", "notes"]]
        st.dataframe(display, use_container_width=True, hide_index=True)

        # Build a friendly label -> id map for the selector.
        options = {}
        for _, r in display.iterrows():
            label = (
                f"#{r['id']} · {r['date']} · {int(r['duration_minutes'])} min · "
                f"{r['participants'] or '—'}"
            )
            options[label] = r["id"]

        selected_label = st.selectbox("Select a session", list(options.keys()))
        selected_id = options[selected_label]
        row = data[data["id"].astype(str) == str(selected_id)].iloc[0]
        # Per-session key suffix so switching rows resets the fields.
        k = f"edit_{selected_id}"

        with st.form("edit_session"):
            e_date = st.date_input(
                "Date", value=sheets.parse_date(row["date"]), format="DD/MM/YYYY",
                key=f"{k}_date",
            )
            e_minutes = pick_minutes(
                default=int(float(row["duration_minutes"] or 0)), key_prefix=k
            )
            e_participants = st.multiselect(
                "Who was this session with?", sheets.PARTICIPANT_OPTIONS,
                default=sheets.parse_participants(row["participants"]),
                key=f"{k}_participants",
            )
            e_extra = st.number_input(
                "Additional independent time (prep, review, reports)",
                min_value=0, value=int(float(row["extra_minutes"] or 0)), step=5,
                key=f"{k}_extra",
                help="In minutes. Added on top of the session length.",
            )
            e_notes = st.text_area("Notes", value=str(row["notes"]), key=f"{k}_notes")

            save_col, del_col = st.columns(2)
            save = save_col.form_submit_button("Save changes", type="primary")
            delete = del_col.form_submit_button("Delete session")

        if save:
            if e_minutes <= 0:
                st.error("Enter a session length greater than 0 minutes.")
            elif not e_participants:
                st.error("Pick at least one person under “Who was this session with?”.")
            else:
                sheets.update_session(
                    selected_id, e_date, int(e_minutes),
                    int(e_extra), ", ".join(e_participants), e_notes.strip(),
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
            data.loc[data["month"] == chosen_period, "total_hours"].sum()
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
            .groupby("month")["total_hours"].sum()
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
