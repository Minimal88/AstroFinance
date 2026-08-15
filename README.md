# AstroFinance

Tracks BAC credit-card transactions from Gmail notification emails, with a phone
app for marking payments and a local web app for filtering and reconciliation.

```
Gmail ──(Apps Script, 15-min trigger)──▶ Google Sheet ◀──(AppSheet: view + mark paid)
                                              │
                                              │ service account, Sheets API
                                              ▼
                                    pull ──▶ SQLite (local cache)
                                              │
                                              ▼
                            FastAPI: filtering, billing periods, CSV reconciliation
```

**The Google Sheet is the system of record.** SQLite is a disposable local
mirror — everything in it can be rebuilt from the Sheet, which is why
`pull --rebuild` is always safe and why payment writes go to the Sheet first.

Ingestion runs on Google's infrastructure via Apps Script, so it keeps working
with your laptop closed. It uses `GmailApp` directly: no OAuth client, no
refresh token, and nothing that breaks when you change your Google password.

## Setup

### 1. Apps Script (ingestion)

Follow [apps_script/README.md](apps_script/README.md) — it covers creating the
spreadsheet, pasting in the script, backfilling history, installing the trigger,
and configuring the AppSheet mobile app.

You will need the exact `From:` address BAC sends notifications from. Nothing
ingests until that is set.

### 2. Python (local web app)

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Create a **service account** in the same Google Cloud project:

1. Enable the **Google Sheets API**.
2. IAM & Admin → Service Accounts → create one → Keys → Add key → JSON.
3. Save it as `credentials/service_account.json`.
4. **Share the spreadsheet with the service account's email address**
   (`...@....iam.gserviceaccount.com`), as **Editor**. Skipping this is the most
   common first-run failure and shows up as a 404.

Service-account keys do not expire, so this never needs re-authorizing.

```bash
cp .env.example .env      # then set SPREADSHEET_ID and BILLING_CUTOFF_DAY
```

## Usage

```bash
.venv/Scripts/python.exe -m astrofinance.cli init-db   # create the database
.venv/Scripts/python.exe -m astrofinance.cli pull      # mirror the Sheet into SQLite
.venv/Scripts/python.exe -m uvicorn astrofinance.web.app:app --reload
```

`pull` upserts by reference and prunes rows deleted from the Sheet.
`--rebuild` reloads from scratch; `--no-prune` keeps local-only rows.

Open http://127.0.0.1:8000 for:

- **Transactions** — filter by date range, cardholder, card and paid/pending,
  with per-currency totals. Defaults to the current billing period, computed
  from `BILLING_CUTOFF_DAY`. "Pull from Sheet" refreshes the mirror.
- **Payments** — record a payment covering a set of pending transactions. The
  bulk checkbox flow is why this stayed in the web app rather than moving to the
  phone. Writes go to the Sheet, then re-pull. Deleting a payment returns its
  transactions to pending.
- **Reconciliation** — upload the bank's CSV export to compare against the
  database. Matches by reference, falling back to amount + date.

Payments marked on the phone in AppSheet reach the web app on the next `pull`.

## Reconciliation CSV mapping

`CSV_COLUMN_MAP` in [astrofinance/reconcile.py](astrofinance/reconcile.py) still
holds placeholder column names. Replace them with the real headers from a BAC
CSV export before reconciliation will match anything.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

Covers the billing-period maths. The email parsing tests live in
`apps_script/Tests.gs` and run from the Apps Script editor, alongside the parser
they now guard.

## Note

`helpers/` is unrelated to AstroFinance — it holds standalone scripts for filling
PALIG insurance claim PDFs.
