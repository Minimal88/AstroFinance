/**
 * Read-only card pages for family members (Dereck, Hannia).
 *
 * Deployed as a web app (Execute as: Me, Who has access: Anyone), so each page
 * reads the Sheet live with the owner's access while the viewer never gets the
 * Sheet itself. Each person has a private link with a random key; the key picks
 * the card, and only that card's rows ever leave the script.
 *
 * Who sees what lives in the Script Property CARD_PAGES, written by
 * setupCardPages():
 *   {"<key>": {"name": "Dereck", "last": "6074", "holder": "DERECK"}, ...}
 * Rotating a key (rotateCardPageKey) breaks the old link immediately.
 */

// Cards that get a page. Matched by last digits plus cardholder name, not
// CardType: BAC's older emails labelled some Amex charges MASTER.
const CARD_PAGE_PEOPLE = [
  { name: 'Dereck', last: '6074', holder: 'DERECK' },
  { name: 'Hannia', last: '7311', holder: 'HANNIA' },
];

// Amex statement: closes on the 27th, due on the 12th of the next month.
const CARD_PAGE_CUTOFF = 27;
const CARD_PAGE_PAY = 12;

function doGet(e) {
  const key = String((e && e.parameter && e.parameter.k) || '');
  const person = cardPages_()[key];
  if (!key || !person) {
    return HtmlService.createHtmlOutput(
      '<p style="font-family:sans-serif;padding:24px">Este enlace no es válido.</p>'
    ).setTitle('AstroFinance');
  }

  const template = HtmlService.createTemplateFromFile('CardPage');
  // JSON goes into a <script type="application/json"> block, so "<" is escaped
  // to keep a merchant name from closing the tag.
  template.payload = JSON.stringify({
    person: person,
    cutoff: CARD_PAGE_CUTOFF,
    pay: CARD_PAGE_PAY,
    generatedAt: new Date().toISOString(),
    txns: cardMovements_(person),
  }).replace(/</g, '\\u003c');

  return template
    .evaluate()
    .setTitle('Amex de ' + person.name)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, viewport-fit=cover');
}

/**
 * One-time: creates a private link for each person in CARD_PAGE_PEOPLE that
 * does not have one yet, and logs every link. Run it after deploying the web
 * app; re-running only logs the existing links.
 */
function setupCardPages() {
  const pages = cardPages_();
  CARD_PAGE_PEOPLE.forEach(function (person) {
    const exists = Object.keys(pages).some(function (k) {
      return pages[k].last === person.last && pages[k].holder === person.holder;
    });
    if (!exists) pages[newCardPageKey_()] = person;
  });
  props_().setProperty('CARD_PAGES', JSON.stringify(pages));
  logCardPageLinks_(pages);
}

/** Gives one person a new link and invalidates the old one. */
function rotateCardPageKey(name) {
  const pages = cardPages_();
  Object.keys(pages).forEach(function (k) {
    if (pages[k].name === name) {
      pages[newCardPageKey_()] = pages[k];
      delete pages[k];
    }
  });
  props_().setProperty('CARD_PAGES', JSON.stringify(pages));
  logCardPageLinks_(pages);
}

function logCardPageLinks_(pages) {
  const base = ScriptApp.getService().getUrl();
  if (!base) {
    Logger.log('Deploy the web app first (Deploy -> New deployment -> Web app), then run this again.');
    return;
  }
  Object.keys(pages).forEach(function (k) {
    Logger.log(pages[k].name + ': ' + base + '?k=' + k);
  });
}

function cardPages_() {
  const raw = props_().getProperty('CARD_PAGES');
  if (!raw) return {};
  try {
    return JSON.parse(raw) || {};
  } catch (err) {
    throw new Error('Script Property CARD_PAGES is not valid JSON. Delete it and run setupCardPages().');
  }
}

function newCardPageKey_() {
  // Two UUIDs without dashes: 244 random bits, safe to put in a URL.
  return (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
}

/** This card's movements, newest first, with paid status and payment date. */
function cardMovements_(person) {
  const txnRange = sheetByName_('Transactions').getDataRange();
  // Display values keep references and dates as typed; raw values give the
  // amount as a number whatever the Sheet's locale.
  const txnValues = txnRange.getDisplayValues();
  const txnRaw = txnRange.getValues();
  const payValues = sheetByName_('Payments').getDataRange().getDisplayValues();
  if (txnValues.length < 2) return [];

  const header = txnValues[0].map(function (h) { return String(h).trim(); });
  const col = function (name) {
    const i = header.indexOf(name);
    if (i < 0) throw new Error('Transactions is missing column ' + name);
    return i;
  };
  const idx = {
    ref: col('Reference'), date: col('TxnDate'), merchant: col('Merchant'), location: col('Location'),
    currency: col('Currency'), amount: col('Amount'), last: col('LastDigits'), holder: col('CardholderName'),
    pid: col('PaymentID'),
  };

  const payDates = {};
  payValues.slice(1).forEach(function (r) {
    const id = String(r[0] || '').trim();
    if (id) payDates[id] = cardPageDate_(r[1]);
  });

  const out = [];
  txnValues.forEach(function (r, i) {
    if (i === 0) return;
    const ref = String(r[idx.ref] || '').trim();
    if (!ref) return;
    if (String(r[idx.last]).trim() !== person.last) return;
    if (String(r[idx.holder]).toUpperCase().indexOf(person.holder) < 0) return;
    const pid = String(r[idx.pid] || '').trim();
    out.push({
      ref: ref,
      date: cardPageDate_(r[idx.date]),
      merchant: String(r[idx.merchant] || '').trim() || '(sin comercio)',
      location: String(r[idx.location] || '').trim().replace(/^,\s*/, ''),
      currency: String(r[idx.currency] || '').trim() || 'CRC',
      amount: cardPageAmount_(txnRaw[i][idx.amount]),
      paid: !!pid,
      payDate: pid ? (payDates[pid] || '') : '',
    });
  });
  out.sort(function (a, b) {
    return (b.date || '').localeCompare(a.date || '') || a.ref.localeCompare(b.ref);
  });
  return out;
}

// The script writes ISO dates; rows typed by hand may show M/D/YYYY.
function cardPageDate_(raw) {
  const t = String(raw || '').trim();
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return m[1] + '-' + ('0' + m[2]).slice(-2) + '-' + ('0' + m[3]).slice(-2);
  m = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (m) return m[3] + '-' + ('0' + m[1]).slice(-2) + '-' + ('0' + m[2]).slice(-2);
  return '';
}

// Normally a number; text amounts look like "15,860.00" or "(1,000.00)".
function cardPageAmount_(raw) {
  if (typeof raw === 'number') return raw;
  const t = String(raw || '').trim();
  const neg = /^\(.*\)$/.test(t) || t.charAt(0) === '-';
  const n = parseFloat(t.replace(/[^\d.]/g, ''));
  return isNaN(n) ? 0 : (neg ? -n : n);
}
