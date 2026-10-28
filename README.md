# AstroFinance

Tracks BAC credit-card transactions from Gmail notification emails, with a phone
app for seeing what is due per card, marking charges as paid and reconciling
the bank statement.

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
- **Conciliar**: upload the bank's CSV export and compare it with the Sheet,
  in the browser (nothing is written).
  - **BAC "Transacciones del mes"** is detected automatically. The app reads
    the summary (card, cutoff, due date, cash and minimum payment), the
    colones and dollars columns, and the card sections. Charges are matched
    to the Sheet by card, currency, amount and date (±3 days, similar
    merchant name first). It also pairs one email with several bank lines
    that add up to it (one airline ticket per passenger), and an email in
    another currency with what the bank charged (EUR or ₡ billed in USD).
    The same merchant on the same day with a different amount is flagged as
    a difference, with an "Aceptar cambio" button that writes the bank's
    amount and currency to the Sheet (columns F and G). IVA, installments, interest and payments are listed on
    their own. Sheet charges from the statement period with no bank line are
    proposed as "En espera", and those after the last posted charge as
    "Prox" (probably in the next statement). Tags can be removed (with a
    confirmation) while reconciling. "Concluir conciliación" writes them to
    the Sheet's Tag column (Q, header added if missing) and clears the tag on
    charges that now appear in the statement. Pendientes shows the tags, and
    "Prox" charges are left out of the sums.
  - **Any other CSV**: the reference, amount and date columns are guessed
    from the headers (Spanish or English, comma or semicolon separated,
    UTF-8 or Windows-1252) and can be corrected; the choice is remembered.
    Rows match by reference or authorization number first, then by amount
    (±0.01) and date (±3 days).

To change the app, edit the file and republish it to the same artifact.

## Tests

The email parsing tests live in `apps_script/Tests.gs` and run from the Apps
Script editor (`runParserTests()`), alongside the parser they guard.

## Note

`helpers/` is unrelated to AstroFinance. It holds standalone scripts for filling
PALIG insurance claim PDFs.
