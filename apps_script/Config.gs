/**
 * Configuration and shared constants.
 *
 * Secrets and per-install values live in Script Properties
 * (Project Settings -> Script Properties), not in this file. That is the
 * Apps Script equivalent of a .env file.
 */

// Column order is the contract shared with the phone app (app/astrofinance.html).
// Apps Script writes positionally; the app reads by header name and writes
// Category and PaymentID by column letter (L and M).
const HEADERS = {
  Transactions: [
    'Reference',
    'TxnDate',
    'Merchant',
    'Description',
    'Location',
    'Currency',
    'Amount',
    'CardType',
    'LastDigits',
    'CardholderName',
    'Authorization',
    'Category',
    'PaymentID',
    'GmailMessageId',
    'GmailPermalink',
    'CreatedAt',
  ],
  Payments: ['PaymentID', 'PaymentDate', 'Amount', 'Currency', 'Notes', 'CreatedAt'],
  ParseErrors: ['GmailMessageId', 'ReceivedAt', 'Subject', 'Error', 'GmailPermalink'],
};

// Columns that must be Plain text ('@') so Sheets does not coerce them.
// Without this, reference 987654321012 becomes a float and authorization
// 091234 loses its leading zero.
const TEXT_COLUMNS = {
  Transactions: ['Reference', 'TxnDate', 'LastDigits', 'Authorization', 'PaymentID', 'GmailMessageId', 'CreatedAt'],
  Payments: ['PaymentID', 'PaymentDate', 'CreatedAt'],
  ParseErrors: ['GmailMessageId', 'ReceivedAt'],
};

// Stop well short of the 6-minute execution limit so a run always finishes
// cleanly rather than being killed mid-append.
const MAX_RUNTIME_MS = 4 * 60 * 1000;
const MAX_MESSAGES_PER_RUN = 50;

// Incremental lookback. Dedup by Reference makes the overlap free, and two
// days of slack self-heals a trigger outage without a fragile cursor.
const INCREMENTAL_WINDOW = 'newer_than:2d';

const TRIGGER_INTERVAL_MINUTES = 15;
const BACKFILL_PAGE_SIZE = 25;

function props_() {
  return PropertiesService.getScriptProperties();
}

function requireProperty_(name) {
  const value = props_().getProperty(name);
  if (!value) {
    throw new Error(
      'Missing Script Property "' + name + '". Set it under Project Settings -> Script Properties.'
    );
  }
  return value;
}

/**
 * The BAC notification address(es).
 *
 * BAC_SENDER_EMAIL may hold a comma-separated list, since BAC sends
 * notifications from more than one address (e.g. a new one added later).
 * Each entry is trimmed, and tolerant of a full "Display Name <addr@host>"
 * header being pasted in: Gmail's from: operator would match nothing for
 * that form, and the Script Properties UI shows no hint that a stray space
 * or the display name is there.
 */
function senderEmails_() {
  const raw = requireProperty_('BAC_SENDER_EMAIL');
  return raw
    .split(',')
    .map(function (part) {
      const trimmed = part.trim();
      const angled = trimmed.match(/<([^>]+)>/);
      return (angled ? angled[1] : trimmed).trim();
    })
    .filter(function (email) {
      return email.length > 0;
    });
}

/** Gmail search fragment matching any of the configured sender addresses. */
function senderQuery_() {
  const clauses = senderEmails_().map(function (email) {
    return 'from:' + email;
  });
  return clauses.length > 1 ? '(' + clauses.join(' OR ') + ')' : clauses[0];
}

function spreadsheet_() {
  return SpreadsheetApp.openById(requireProperty_('SPREADSHEET_ID'));
}
