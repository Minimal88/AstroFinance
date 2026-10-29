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

- **Menu**: the ☰ button in the header opens the sections (Pendientes,
  Movimientos, Conciliar, Pagos), a link to the Presupuesto page, links to
  Dereck's and Hannia's Amex pages and Dereck's motorcycle page (open one to
  publish fresh data to it), and Ajustes.
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

## Presupuesto (monthly budget)

[`app/presupuesto.html`](app/presupuesto.html) is the owner's monthly budget,
based on the old "Presupuesto 2026" sheet. It reads and writes the
`Presupuesto` tab of the same Sheet through the owner's Google Sheets
connector (nobody else sees it, so there is no published copy):

| Tipo | Concepto | Monto | Moneda | Quincena | Grupo | Hasta | Notas | | TipoCambio | MetaSaldo |
|---|---|---|---|---|---|---|---|---|---|---|

- `Tipo` is `Ingreso`, `Deducción`, `Gasto` or `Ahorro`. `Moneda` is `USD`,
  `CRC` or `%` (deductions only: a percentage of the gross income).
- `Quincena` is `1` or `2` (that payday only), `Ambas` (the amount comes or
  goes every payday, so it counts twice a month, like the salary and its
  deductions from the pay stub) or blank (a monthly amount split between both
  paydays). `Grupo` is
  `Casa`, `Transporte`, `Salud`, `Personal` or `Otros`; `Ahorro` lines have
  their own group.
- `Hasta` is an optional `MM/YYYY` (the page writes it with a leading `'` so
  Sheets keeps it as text; a date serial is also read): once that month has passed the line moves
  to "Ya terminaron" and stops counting.
- `J2` holds the colones per dollar rate and `K2` the goal for what is left
  over (`10-20`, as a % of net income).
- The page shows what is left each month against that goal, then "Tus
  quincenas": for the chosen payday, the net pay coming in, a marker where
  spending starts, and each line that falls on it in the order of the
  sheet's rows, with what is left after each one. Then how the net income
  splits by group, income and deductions, and every line by group (each
  card folds; the page remembers which), in colones or dollars. Tapping a line
  edits it (after checking the row still holds it); "Agregar línea" fills the
  first empty row; deleting clears the row.

## Amex pages for Dereck and Hannia

[`app/amex-dereck.html`](app/amex-dereck.html) and
[`app/amex-hannia.html`](app/amex-hannia.html) are read-only pages, each
published as its own artifact. They show one Amex card's movements (paid or
pending, with the payment date) grouped by Amex statement, plus the next
payment and everything still pending. They have the main app's period chips
(Próximo pago, Siguiente estado, Estado anterior, Todo) plus Todos / Pendientes
/ Pagados. Nobody can mark payments from them.

- **Which rows**: by last digits and cardholder name (6074 + DERECK, 7311 +
  HANNIA), not by CardType, because some of Dereck's Amex emails were parsed as
  MASTER.
- **No sheet access for them**: the page keeps a copy of that card's rows
  inside itself. When the owner opens it, it reads the Sheet live through the
  owner's Google Sheets connector and, if anything changed, offers
  "Publicar para Dereck/Hannia", which republishes the page with the new copy.
  Dereck and Hannia only ever see that published copy, never the Sheet.
- The two files are identical except for the `VIEWER` line and the title. The
  files in the repo carry no data (`snapshot` is `null`), so republishing one
  from the repo empties it until the owner taps "Publicar" again.

## Dereck's motorcycle page

[`app/moto-dereck.html`](app/moto-dereck.html) tracks the 24 Mastercard
installments for Dereck's motorcycle: which ones Dereck has paid back, and
which ones have been paid to the card. It reads the `MotoDereck` tab of the
same Sheet (copied from the old "Pagos Moto de Dereck" workbook):

| Cuota | FechaCobro | Monto | DereckPagado | DereckFecha | TarjetaPagada | TarjetaFecha | Notas |
|---|---|---|---|---|---|---|---|

- Dates are stored as `yyyy-mm-dd` text; dates typed by hand are read as
  d/m/yyyy. `DereckPagado` and `TarjetaPagada` are `Sí` or `No`.
- Tiles show what Dereck has paid, what has been paid to the Mastercard, the
  next installment, and "Cuotas adelantadas": how many installments Dereck has
  paid ahead that sit in Wink. That counter is set by hand in `J2`
  (header `CuotasAdelantadas` in `J1`); the owner changes it with the − / +
  buttons. The card payment for an installment is due on the 5th of the
  following month.
- **Owner**: tapping an installment opens a form to tick "Dereck me pagó" and
  "Pagué la Mastercard" with their dates and notes. It writes columns D:H of
  that row, after checking the row still holds that installment.
- **Dereck**: same publish model as the Amex pages. He sees the last copy
  published with "Publicar para Dereck" and never the Sheet. The repo file has
  no data (`snapshot` is `null`).

## Tests

The email parsing tests live in `apps_script/Tests.gs` and run from the Apps
Script editor (`runParserTests()`), alongside the parser they guard.

## Note

`helpers/` is unrelated to AstroFinance. It holds standalone scripts for filling
PALIG insurance claim PDFs.
