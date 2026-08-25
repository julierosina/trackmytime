# Track your time! Please and thank you

A minimal Streamlit app to track the hours a tutor actually works each month.
The tutor is paid a flat monthly fee for a set number of contracted hours but
often works more — this app logs each session, computes real hours worked, and
compares them to the contracted amount so the gap is visible for future rate
negotiations.

Data is stored in a single **Google Sheet** worksheet via `gspread` and a
Google **service account**. Credentials come from `st.secrets`, so the same code
runs locally and on Streamlit Community Cloud.

## Features

- **Log a session** — date (defaults to today), start/end time, student, subject,
  notes. Duration is computed automatically; end time must be after start time.
- **Edit / delete** — pick any past session, change its fields (duration
  recalculates), or delete it. Changes write straight back to the sheet.
- **Monthly summary** — total hours logged this month, an editable contracted-hours
  figure, and the over/under difference.
- **History** — a bar chart + table of total hours per month over time.

## Files

| File               | Purpose                                             |
| ------------------ | --------------------------------------------------- |
| `app.py`           | Streamlit UI (four tabs)                            |
| `sheets.py`        | Google Sheets read/write helpers                    |
| `requirements.txt` | Python dependencies                                 |

---

## 1. Set up the Google Sheet

1. Create a new Google Sheet (any name, e.g. `Tutor Hours`).
2. Rename the first worksheet/tab to **`Sessions`** (or keep the default and set
   `worksheet` in secrets — see below).
3. Put these **exact column headers** in row 1, in this order:

   ```
   id | date | start_time | end_time | duration_hours | extra_minutes | participants | notes
   ```

   `participants` holds who a session involved — one or more of `Student`,
   `Nico`, `Company`, `Just me (prep/reports)`, stored comma-separated
   (e.g. `Student, Company`). `extra_minutes` is optional independent time
   (prep/review/reports) in minutes, added on top of the session length when
   totals are computed.

   > If you leave the sheet empty, the app writes these headers automatically on
   > first run — but only if row 1 is blank.

Data conventions written by the app:

- `id` — incrementing integer (1, 2, 3, …)
- `date` — `YYYY-MM-DD`
- `start_time` / `end_time` — `HH:MM` (24-hour)
- `duration_hours` — decimal hours (e.g. `1.5`)

## 2. Create a Google service account

1. In the [Google Cloud Console](https://console.cloud.google.com/), create (or
   pick) a project.
2. Enable the **Google Sheets API** and the **Google Drive API** for it.
3. Go to **APIs & Services → Credentials → Create credentials → Service account**.
4. Once created, open the service account → **Keys → Add key → Create new key →
   JSON**. This downloads the JSON key file you already have.

## 3. Share the sheet with the service account

Open the JSON key and copy the value of `client_email` — it looks like
`something@your-project.iam.gserviceaccount.com`.

In the Google Sheet, click **Share** and add that email address with **Editor**
access. Without this, the app can authenticate but can't read or write the sheet.

## 4. Add credentials to secrets

The app reads two things from `st.secrets`:

- `[gcp_service_account]` — the full contents of your service-account JSON key.
- `[sheet]` — which spreadsheet/worksheet to use.

### Local development (`.streamlit/secrets.toml`)

Create `.streamlit/secrets.toml` next to `app.py`:

```toml
[sheet]
# Any of: the spreadsheet key, its full URL, or its exact title.
# The key is the long token in the URL:
#   https://docs.google.com/spreadsheets/d/THIS_LONG_TOKEN/edit
spreadsheet = "THIS_LONG_TOKEN"
worksheet   = "Sessions"        # optional; defaults to "Sessions"

[gcp_service_account]
type                        = "service_account"
project_id                  = "your-project-id"
private_key_id              = "..."
# Keep the literal \n sequences in the private key exactly as in the JSON,
# wrapped in triple quotes:
private_key                 = """-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"""
client_email                = "svc@your-project.iam.gserviceaccount.com"
client_id                   = "..."
auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
token_uri                   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url        = "https://www.googleapis.com/robot/v1/metadata/x509/svc%40your-project.iam.gserviceaccount.com"
universe_domain             = "googleapis.com"
```

> **Do not commit `secrets.toml`.** Add `.streamlit/secrets.toml` to `.gitignore`.

### Streamlit Community Cloud

Deploy the repo, then in the app dashboard go to **Settings → Secrets** and paste
the **same TOML content** as above (the `[sheet]` and `[gcp_service_account]`
sections). Save — the app restarts and picks them up. No JSON file is uploaded;
the credentials live only in the secrets manager.

---

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- The contracted-hours value is a single configurable number in the Monthly
  summary tab (single-student use case); it isn't stored per student.
- Sheet reads are cached (`st.cache_data`, 5-minute TTL) to avoid hammering the
  Sheets API; the cache is cleared automatically after any add/edit/delete.
