# AstroFinance

Tracks BAC credit-card transactions from Gmail notification emails, with a phone
app for seeing what is due per card and marking charges as paid.

```
Gmail ──(Apps Script, 15-min trigger)──▶ Google Sheet ◀──(phone app: view + mark paid)
```

**The Google Sheet is the system of record.** Every write goes straight to it,
and the phone app reads it fresh each time it opens.

Ingestion runs on Google's infrastructure via Apps Script, so it keeps working
with your laptop closed. It uses `GmailApp` directly: no OAuth client, no
refresh token, and nothing that breaks when you change your Google password.

## Setup

### 1. Apps Script (ingestion)

Follow [apps_script/README.md](apps_script/README.md). It covers creating the
spreadsheet, pasting in the script, backfilling history and installing the
trigger.

You will need the exact `From:` address BAC sends notifications from. Nothing
ingests until that is set.

### 2. Phone app

[`app/astrofinance.html`](app/astrofinance.html) is a single-page app published
as a Claude artifact. It reads and writes the Sheet through the viewer's Google
Sheets connector in claude.ai, so there is nothing to install or host and no
service account. The first time it opens, claude.ai asks for permission to use
Google Sheets. The spreadsheet ID can be changed in the app's settings.

## Phone app

- **Pendientes**: pending charges grouped by cardholder. A tile per card family
  shows when its next payment is due, the statement total and what is still
  pending; tapping a tile filters to that card.
- **Statements per card family**: Visa and Mastercard close on the 21st and are
  due on the 5th of the next month; Amex closes on the 27th and is due on the
  12th. A statement runs from the day after the previous cutoff through the
  cutoff day. Switch between the next payment, the following statement, the
  previous one, or everything. Both days can be changed in the app's settings.
- **Marcar pagado**: creates a row in Payments (or adds to an existing one) and
  writes its PaymentID onto the selected transactions. It re-reads the Sheet
  first so a payment set elsewhere is not overwritten.
- **Pagos**: each payment shows whether it matches the transactions it covers.
- **Detail**: editable category, link to the original email, and "back to
  pending".

To change the app, edit the file and republish it to the same artifact.

## Tests

The email parsing tests live in `apps_script/Tests.gs` and run from the Apps
Script editor (`runParserTests()`), alongside the parser they guard.

## Note

`helpers/` is unrelated to AstroFinance. It holds standalone scripts for filling
PALIG insurance claim PDFs.
