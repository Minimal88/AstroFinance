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

## Phone app (Claude artifact)

[`app/astrofinance.html`](app/astrofinance.html) is a single-page app published as
a Claude artifact. It replaces the AppSheet app. It reads and writes the same
Google Sheet through the viewer's Google Sheets connector in claude.ai, so it
needs no service account.

- **Pendientes**: pending charges grouped by cardholder. A tile per card family
  shows when its next payment is due and what that statement holds.
- **Statements per card family**: Visa and Mastercard close on the 21st and are
  due on the 5th; Amex closes on the 27th and is due on the 12th. A statement
  runs from the day after the previous cutoff through the cutoff day. Both days
  can be changed in the app's settings.
- **Marcar pagado**: creates a row in Payments (or reuses one) and writes its
  PaymentID onto the selected transactions. It re-reads the Sheet first so a
  payment set elsewhere is not overwritten.
- **Pagos**: each payment shows whether it matches the transactions it covers.

To change the app, edit the file and republish it to the same artifact.

## Reconciliation CSV mapping

The reconciliation page guesses the reference, amount and date columns from the
CSV headers (Spanish and English names both work). If a guess is wrong, pick the
right columns from the dropdowns and re-run; the choice is remembered in a
cookie and reused for the next upload with the same headers.

Matching rules:

- By reference first, then by amount within ±0.01 and date within
  `DATE_TOLERANCE_DAYS` (3) of the statement row, closest date first.
- Each transaction matches at most one statement row.
- Amounts are compared as absolute values, so it does not matter whether the
  bank exports charges as positive or negative.
- "In database but not in statement" only covers the dates the statement spans.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

Covers the billing-period maths and statement reconciliation. The email parsing tests live in
`apps_script/Tests.gs` and run from the Apps Script editor, alongside the parser
they now guard.

## Note

`helpers/` is unrelated to AstroFinance — it holds standalone scripts for filling
PALIG insurance claim PDFs.
