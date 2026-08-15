/**
 * All Google Sheets access.
 *
 * Two rules the rest of the system depends on:
 *   1. Identifier columns are Plain text before the first write, so Sheets
 *      never coerces reference 987654321012 into a float or strips the
 *      leading zero from authorization 091234.
 *   2. Rows are only ever appended at the bottom. Never insert, sort or
 *      reorder -- AppSheet caches row positions and reordering confuses its
 *      sync.
 */

/**
 * One-time, idempotent. Creates the tabs, writes headers, freezes row 1 and
 * applies plain-text formatting. Safe to re-run.
 */
function setupSheets() {
  const ss = spreadsheet_();

  Object.keys(HEADERS).forEach(function (tabName) {
    const headers = HEADERS[tabName];
    let sheet = ss.getSheetByName(tabName);
    if (!sheet) {
      sheet = ss.insertSheet(tabName);
    }

    sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    sheet.setFrozenRows(1);

    // Format the whole column, header included, before any data lands.
    (TEXT_COLUMNS[tabName] || []).forEach(function (columnName) {
      const index = headers.indexOf(columnName);
      if (index >= 0) {
        sheet.getRange(1, index + 1, sheet.getMaxRows(), 1).setNumberFormat('@');
      }
    });

    const amountIndex = headers.indexOf('Amount');
    if (amountIndex >= 0) {
      sheet.getRange(2, amountIndex + 1, sheet.getMaxRows() - 1, 1).setNumberFormat('#,##0.00');
    }
  });

  const defaultSheet = ss.getSheetByName('Sheet1');
  if (defaultSheet && ss.getSheets().length > 1) {
    ss.deleteSheet(defaultSheet);
  }

  Logger.log('setupSheets complete: ' + Object.keys(HEADERS).join(', '));
}

function sheetByName_(tabName) {
  const sheet = spreadsheet_().getSheetByName(tabName);
  if (!sheet) {
    throw new Error('Missing tab "' + tabName + '". Run setupSheets() first.');
  }
  return sheet;
}

/**
 * One column of a tab as a Set of non-empty trimmed strings, in one read.
 * Looked up by header name rather than by index so the column contract lives
 * in exactly one place (HEADERS).
 */
function columnSet_(tabName, columnName) {
  const index = HEADERS[tabName].indexOf(columnName);
  if (index < 0) {
    throw new Error('No column "' + columnName + '" on tab "' + tabName + '".');
  }

  const sheet = sheetByName_(tabName);
  const lastRow = sheet.getLastRow();
  const values = new Set();
  if (lastRow < 2) return values;

  sheet.getRange(2, index + 1, lastRow - 1, 1).getValues().forEach(function (row) {
    const value = String(row[0] || '').trim();
    if (value) values.add(value);
  });
  return values;
}

/** Every Reference already stored, as a Set, in one read. */
function loadReferenceSet_() {
  return columnSet_('Transactions', 'Reference');
}

/** Appends rows in a single setValues call. No-op on an empty array. */
function appendRows_(tabName, rows) {
  if (!rows || rows.length === 0) return 0;
  const sheet = sheetByName_(tabName);
  sheet
    .getRange(sheet.getLastRow() + 1, 1, rows.length, HEADERS[tabName].length)
    .setValues(rows);
  return rows.length;
}

function nowIso_() {
  return Utilities.formatDate(new Date(), 'America/Costa_Rica', "yyyy-MM-dd'T'HH:mm:ss");
}

function permalinkFor_(message) {
  return 'https://mail.google.com/mail/u/0/#all/' + message.getId();
}

/**
 * The Reference a message is stored under -- BAC's own, or a stand-in derived
 * from the Gmail message id when the email omitted it.
 *
 * Reference is the AppSheet key and the dedup key, so it cannot be blank. The
 * message id makes the stand-in stable across re-ingestion (so dedup still
 * holds and re-running the backfill stays free) and unique (message ids are).
 * The prefix keeps it from ever being mistaken for a real BAC reference.
 *
 * The one thing this cannot do is recognise a referenceless transaction that
 * BAC sends twice as two different emails -- with no reference there is
 * nothing to match on, so that would store two rows. Visible and deletable,
 * unlike the alternative of storing none.
 */
function referenceFor_(parsed, message) {
  return parsed.reference || 'GM-' + message.getId();
}

/** Maps a parsed transaction plus its source message onto a Transactions row. */
function toTransactionRow_(parsed, message) {
  return [
    referenceFor_(parsed, message),
    parsed.txnDate,
    parsed.merchant,
    parsed.description,
    parsed.location,
    parsed.currency,
    parsed.amount,
    parsed.cardType,
    parsed.lastDigits,
    parsed.cardholderName,
    parsed.authorization,
    '', // Category  - filled in from AppSheet
    '', // PaymentID - filled in from AppSheet or FastAPI
    message.getId(),
    permalinkFor_(message),
    nowIso_(),
  ];
}

function toErrorRow_(message, error) {
  return [
    message.getId(),
    Utilities.formatDate(message.getDate(), 'America/Costa_Rica', "yyyy-MM-dd'T'HH:mm:ss"),
    message.getSubject(),
    String(error && error.message ? error.message : error),
    permalinkFor_(message),
  ];
}

/**
 * A ParseErrors row for a transaction that WAS stored but has blank cells.
 * ParseErrors doubles as the to-do list: every row here is either mail to
 * ignore or a transaction needing a human look, and nothing is silently wrong.
 *
 * The Reference goes in the message text because this tab has no Reference
 * column -- its header order is a contract with the Python client. That string
 * is what you paste into Ctrl+F on the Transactions tab to find the row.
 */
function toWarningRow_(message, reference, warnings) {
  return [
    message.getId(),
    Utilities.formatDate(message.getDate(), 'America/Costa_Rica', "yyyy-MM-dd'T'HH:mm:ss"),
    message.getSubject(),
    'Stored as ' + reference + ', with gaps: ' + warnings.join('; '),
    permalinkFor_(message),
  ];
}
