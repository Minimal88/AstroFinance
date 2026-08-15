# AstroFinance Apps Script

Ingests BAC transaction notification emails from Gmail into a Google Sheet, on a
15-minute timer, running on Google's infrastructure. No OAuth client, no refresh
token, nothing that breaks when you change your Google password.

The Sheet is the system of record. AppSheet reads it on your phone; the Python
app mirrors it into SQLite for reconciliation and detailed filtering.

## Files

Apps Script concatenates every `.gs` file into one global scope, so file order
does not matter.

| File | Purpose |
|---|---|
| `appsscript.json` | Manifest: timezone, V8 runtime, OAuth scopes |
| `Config.gs` | Script Properties accessors, column contract, runtime budgets |
| `Parser.gs` | Email HTML → transaction object (port of `astrofinance/parser.py`) |
| `SheetStore.gs` | `setupSheets()`, dedup set, batched appends |
| `Ingest.gs` | `runIncrementalSync()`, backfill, trigger install |
| `Tests.gs` | `runParserTests()` — 39 assertions; `debugParseLatest()` |
| `Diagnostics.gs` | `auditCoverage()`, `diagnoseSender()`, `listBacSenders()` — troubleshooting |

There is no `clasp` setup. Six files that change maybe twice a year do not
justify a Node toolchain plus another long-lived secret to keep out of git.
**Edit here, paste into the Apps Script editor, commit.**

## Setup

### 1. Create the spreadsheet

Create a Google Sheet named `AstroFinance`. Copy its ID from the URL:
`docs.google.com/spreadsheets/d/`**`<THIS_PART>`**`/edit`

Set **File → Settings → Time zone** to `(GMT-06:00) Costa Rica` so it matches
the script manifest.

### 2. Create the Apps Script project

Go to [script.google.com](https://script.google.com) → **New project**. Make it
a **standalone** project, not one bound to the Sheet — a bound script dies with
the Sheet and cannot be repointed.

Create one file per `.gs` above (the editor's ⚙️ **Project Settings → Show
`appsscript.json`** exposes the manifest) and paste the contents in.

### 3. Script Properties

**Project Settings → Script Properties**, add:

| Property | Value |
|---|---|
| `BAC_SENDER_EMAIL` | The exact `From:` address on a real BAC notification email |
| `SPREADSHEET_ID` | The ID from step 1 |

`BAC_SENDER_EMAIL` is the one value nothing works without. Open a BAC
transaction email, show the original/details, and copy the sender address
verbatim.

Don't know it? Run **`listBacSenders`** — it tallies the `From:` addresses of
anything in the mailbox that looks like a bank notification and prints them
most-frequent first, with a sample subject each.

### 4. Build the tabs

Run **`setupSheets`** once. On first run Google shows an "this app isn't
verified" interstitial — that is expected for a personal script, click
**Advanced → Go to AstroFinance (unsafe)**.

This creates `Transactions`, `Payments` and `ParseErrors`, writes the headers,
freezes row 1, and — critically — sets the identifier columns to **Plain text**.
That formatting must exist *before* the first write, otherwise Sheets turns
reference `987654321012` into a float and eats the leading zero in
authorization `091234`.

### 5. Check the parser

Run **`runParserTests`**, then **View → Logs**. Expect
`ALL 39 ASSERTIONS PASSED`.

Then run **`debugParseLatest`** and eyeball the parsed output of a real BAC
email. This is what catches template changes the synthetic sample does not
cover.

If it logs `No messages found for that sender`, the parser is fine and the
Gmail query matched nothing. Run **`diagnoseSender`**: it prints the account
the script is authorized as, the property value with quotes around it (so a
stray space or newline is visible), and the hit count for four query shapes.
`0` for `from:<addr>` but non-zero for `in:anywhere from:<addr>` means the mail
is in Spam or Trash — `GmailApp.search()` skips both — so fix that in Gmail
rather than adding `in:anywhere` to the query. `0` everywhere means the address
is wrong: run `listBacSenders`.

### 6. Backfill the history

```
backfillStart()    # pins a `before:` date so paging stays deterministic
backfillRun()      # run repeatedly, from the editor, until it logs COMPLETE
backfillStatus()   # where am I
backfillReset()    # start over
```

Run `backfillRun()` **manually and repeatedly**. Each call works for about 4
minutes and persists its offset, so re-running resumes where it stopped. Manual
executions do not draw on the 90 min/day trigger quota, which makes the whole
backfill free.

**Do not install the trigger until this logs `BACKFILL COMPLETE`.**

Then run **`auditCoverage`**. It walks every message from the sender and checks
that each one is accounted for: stored in `Transactions`, logged in
`ParseErrors`, or a repeat of a `Reference` already stored. Each unaccounted
message is re-parsed and printed with a date, subject, permalink and a verdict.

**Do not sanity-check by comparing row counts against Gmail's result count.**
Gmail counts *threads*; the Sheet stores one row per *message*; BAC reuses
subject lines so one thread routinely holds several transactions. The two
numbers are not supposed to match, in either direction. `auditCoverage`
compares Gmail message IDs, which is exact.

Verdicts and what to do:

| Verdict | Meaning |
|---|---|
| `DUPLICATE` | BAC sent the same transaction twice. Skipped deliberately — no action |
| `NOT A TXN` | A statement, promotion or alert — correctly not a row. Never scanned, though; had it been, it would be in `ParseErrors` |
| `MISSING` | Parses fine but is not in the Sheet |

The audit's **first line** states whether the incremental sync is installed and
how far back it currently reaches. Read it first: every "the next run picks this
up" below is worthless if nothing is running.

`MISSING` carries a parenthesised note naming the cause:

- **After the backfill boundary** — out of scope by design. `backfillStart()`
  pins `before:<today>` so paging by offset stays deterministic while new mail
  keeps arriving; without it, each email that lands mid-backfill shifts the
  result set and a whole page gets skipped. It is bookkeeping for one run, not a
  limit on how far back the Sheet goes, and it is inert once the backfill
  reports COMPLETE. Everything newer belongs to the 15-minute sync.

  The boundary is a *day wide*, not a point: Gmail resolves `before:` in a
  timezone of its own, and Costa Rica is UTC-6, so an evening transaction on the
  day *before* it is already the next day in UTC and falls outside the query
  too. Both days get the note.

  The note then says what actually closes the gap — the next sync run, or, if
  the mail has aged past `newer_than:2d`, a backfill, because no number of sync
  runs will ever reach back that far.
- **In Spam or Trash** — fix it in Gmail. `GmailApp.search()` reaches neither, so
  re-running the backfill cannot help.

A `MISSING` with **no note** is the real thing: re-run `backfillReset()` →
`backfillStart()` → `backfillRun()`; re-ingesting is free because dedup is by
`Reference`.

Then open the `ParseErrors` tab, which holds two different kinds of row — the
`Error` column says which:

- **`Stored as … , with gaps: …`** — a real transaction that *is* in
  `Transactions`, with one or more cells blank. Open the permalink, fill the
  cells in by hand, delete the `ParseErrors` row. This tab is the to-do list.
- **`ParseError: not a transaction notification`** — a statement, promotion or
  security alert. Expected, and deliberately not a row. But read the `Subject`:
  if it looks like a purchase, the BAC template changed and `Parser.gs` needs a
  look.

A `Reference` beginning **`GM-`** is a stand-in key for a transaction BAC sent
without a `Referencia` — derived from the Gmail message id, so it is stable and
unique. It is a normal row in every other respect.

Also eyeball the Sheet:
- `=COUNTA(A2:A)` equals `=COUNTA(UNIQUE(A2:A))` — no duplicate references
- `Reference` is left-aligned text, not right-aligned scientific notation

### 7. Install the trigger

Run **`installTrigger`** — `runIncrementalSync` every 15 minutes. Verify under
the ⏰ **Triggers** tab. `removeTrigger()` undoes it.

Make a small card purchase and confirm the row appears within ~15 minutes.
Check **Executions** for green runs taking a few seconds each.

## How it stays correct

- **Dedup is by `Reference`**, read out of the Sheet on every run. That is why
  no Gmail label bookkeeping is needed and why reprocessing an email is free.
- **The incremental window is `newer_than:2d`.** The overlap costs nothing and
  two days of slack self-heals a trigger outage without a fragile cursor.
- **Every message in a thread is processed.** BAC reuses subject lines, so Gmail
  groups many transactions into one thread; reading only the first message would
  silently drop most of them.
- **A missing field never costs the transaction.** The parser records what it
  could not read in `warnings` instead of throwing; the row is written with
  blank cells *and* logged in `ParseErrors`. BAC really does send purchase
  notifications with no `Referencia`, and a row with one gap can be fixed from
  the linked email — one that never arrives is indistinguishable from a month
  you didn't spend anything. The only hard rejection is mail that is not a
  transaction notification at all, so statements and promotions stay out.
- **Every run log balances.** Runs report `N messages scanned = X new + Y
  already stored + Z not a transaction`. Every scanned message lands in exactly
  one bucket, so a smaller-than-expected row count always has a stated reason
  instead of being an unanswerable question later. Rows with gaps are reported
  separately, since they are counted in `X` *and* listed in `ParseErrors`.
- **`auditCoverage()` is the invariant check**, on demand: every message from
  the sender is stored, logged, or a duplicate `Reference`. Run it whenever the
  numbers look wrong.
- **`LockService`** prevents a manual run and a trigger run from double-appending.
- **Runs self-limit** to ~4 minutes and 50 messages, well inside the 6-minute
  execution ceiling.
- **Dates are ISO strings in plain-text cells**, never Sheets Date values, so no
  timezone can shift them.
- **Rows are only ever appended.** Never sort, insert or reorder `Transactions`
  — AppSheet caches row positions.

## Quota

Consumer `@gmail.com` accounts get **90 minutes/day** of total trigger runtime
and **6 minutes** per execution. An idle run is a few seconds, so 96 runs/day
lands around 6–8 minutes — roughly 10× headroom. If quota errors ever appear,
lower `TRIGGER_INTERVAL_MINUTES` to 30 in `Config.gs` and re-run
`installTrigger()`.

## AppSheet app (manual, ~20–30 min)

Do this **after** the backfill — AppSheet infers column types from existing
data, so an empty Sheet produces a useless first guess.

1. [appsheet.com](https://www.appsheet.com) → sign in with the same Google
   account → **Create → App → Start with existing data** → **Google Sheets** →
   the `AstroFinance` spreadsheet → the **`Transactions`** tab.
2. **Data → Tables → New Table** → same spreadsheet → **`Payments`** tab.
   Do **not** add `ParseErrors`.

### Transactions columns (Data → Columns)

3. **Check KEY on `Reference`, then uncheck KEY on `_RowNumber`.** This is the
   single most important click on the page — a `_RowNumber` key breaks every
   row's identity if the Sheet is ever sorted.
4. `TxnDate` → **Date**.
5. `Amount` → **Decimal**, 2 places. Not *Price*: Price pins one currency
   symbol and this feed carries both CRC and USD.
6. `Currency` → **Enum** (`CRC`, `USD`). `CardType` → **Enum** (`VISA`,
   `MASTER`, `AMEX`, `UNKNOWN`).
7. `CardholderName` → **Enum**, "Allow other values" ON.
8. `Category` → **Enum**, "Allow other values" ON, **EDITABLE? ON**.
9. **`PaymentID` → type `Ref`, source table `Payments`.** This is the
   many-transactions-to-one-payment link; AppSheet auto-creates the reverse
   `Related Transactions` column on Payments.
10. `GmailPermalink` → **Url** (tapping it opens the original email).
    `GmailMessageId`, `CreatedAt` → **SHOW? OFF**.
11. Set **EDITABLE? OFF** on everything the script writes (`Reference` through
    `Authorization`, `GmailMessageId`, `CreatedAt`). Only `Category` and
    `PaymentID` should be editable — this stops a fat-finger on the phone from
    corrupting ingested data.

### Payments columns

12. **KEY on `PaymentID`**, uncheck `_RowNumber`; **INITIAL VALUE `UNIQUEID()`**.
13. `PaymentDate` → Date, initial value `TODAY()`. `Amount` → Decimal.
    `Currency` → Enum. `Notes` → LongText. `CreatedAt` → DateTime, initial
    value `NOW()`, SHOW OFF.
14. Virtual column `CoveredTotal` = `SUM([Related Transactions][Amount])`.
15. Virtual column `Delta` = `[Amount] - [CoveredTotal]`.

### Slices, actions, views

16. Slice `Pending` — Transactions, filter `ISBLANK([PaymentID])`.
17. Slice `Recent` — Transactions, filter `[TxnDate] >= (TODAY() - 30)`.
18. Action `Mark paid (latest)` — on Transactions, set `PaymentID` =
    `INDEX(ORDERBY(Payments[PaymentID], [PaymentDate], TRUE), 1)`, prominence
    **Display inline**. Works on multi-selected rows.
19. Action `Unmark` — same, `PaymentID` = `""`.
20. View **Pending** (primary, leftmost): source `Pending`, Table, group by
    `CardholderName`, aggregate **SUM of Amount**, sort `TxnDate` desc.
21. View **Recent**: source `Recent`, grouped by `Currency` with SUM.
22. View **Payments**: source Payments, sorted by `PaymentDate` desc.

Exact billing-period maths deliberately stays in `astrofinance/billing.py`,
where it has tests. A rolling 30 days is the right mobile affordance.

### Onto the phone

23. **Save**, then install the **AppSheet** app from the App Store / Play Store
    and sign in with the same Google account — the app appears automatically.
24. **Stay in prototype / not-deployed mode.** That is the free tier (owner plus
    up to 10 test users). Do not click **Deploy**, and do not build
    Automation/Bots — the Apps Script already does the ingestion.

**AppSheet does not see external Sheet writes in real time.** Rows appended by
the script show up on the next app sync (open the app or pull to refresh). This
is normal, not a broken trigger.
