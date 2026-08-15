/**
 * Port of astrofinance/parser.py.
 *
 * The Python version uses BeautifulSoup. Apps Script has no HTML parser --
 * XmlService.parse() is strict XML and chokes on real email HTML -- so this
 * works over the markup with regexes, structured to mirror the Python
 * extract_table_value() semantics: find the row containing a label cell, take
 * the next non-empty cell in that row.
 *
 * One deliberate difference: normalizeLabel_ strips accents, so this matches
 * "Ciudad y pais" with or without the accent. The Python matcher compared the
 * accented form literally. This is a superset, not a divergence.
 */

const SPANISH_MONTHS = {
  ene: 1, feb: 2, mar: 3, abr: 4, may: 5, jun: 6,
  jul: 7, ago: 8, sep: 9, oct: 10, nov: 11, dic: 12,
};

const CARD_TYPES = ['VISA', 'MASTER', 'AMEX'];

// Labels that only appear on a transaction notification. Statements and
// promotions from the same address carry none of them -- their tables use
// different labels ("Fecha de corte", "Monto a pagar"), and the lookup is an
// exact match on the normalized key, so those do not count.
//
// The threshold is deliberately low. A junk row in Transactions is visible and
// deletable; a dropped transaction is invisible. When in doubt, store it.
const TRANSACTION_LABELS = [
  'Comercio', 'Fecha', 'Monto', 'Referencia', 'Autorizacion', 'Tipo de Transaccion',
];
const MIN_TRANSACTION_LABELS = 2;

const AMOUNT_RE = /([A-Za-z]{3})\s*([\d.,]+)/;
const GREETING_RE = /^Hola\s+(.+)$/i;
const DIGITS_RE = /(\d{3,4})\s*$/;

const NAMED_ENTITIES = {
  nbsp: ' ', quot: '"', apos: "'", lt: '<', gt: '>',
  aacute: 'á', eacute: 'é', iacute: 'í', oacute: 'ó', uacute: 'ú',
  Aacute: 'Á', Eacute: 'É', Iacute: 'Í', Oacute: 'Ó', Uacute: 'Ú',
  ntilde: 'ñ', Ntilde: 'Ñ', uuml: 'ü', Uuml: 'Ü',
};

function decodeEntities_(text) {
  if (!text) return '';
  let out = text.replace(/&([a-zA-Z]+);/g, function (match, name) {
    // &amp; is handled last so "&amp;nbsp;" does not decode twice.
    if (name === 'amp') return match;
    return Object.prototype.hasOwnProperty.call(NAMED_ENTITIES, name) ? NAMED_ENTITIES[name] : match;
  });
  out = out.replace(/&#x([0-9a-fA-F]+);/g, function (_, hex) {
    return String.fromCharCode(parseInt(hex, 16));
  });
  out = out.replace(/&#(\d+);/g, function (_, dec) {
    return String.fromCharCode(parseInt(dec, 10));
  });
  return out.replace(/&amp;/g, '&');
}

function stripTags_(html) {
  return (html || '').replace(/<[^>]*>/g, ' ');
}

/** Tag-stripped, entity-decoded, whitespace-collapsed text of a cell. */
function cellText_(html) {
  return decodeEntities_(stripTags_(html)).replace(/\s+/g, ' ').trim();
}

function rowsOf_(html) {
  return (html || '').match(/<tr[\s\S]*?<\/tr>/gi) || [];
}

function cellsOf_(rowHtml) {
  return (rowHtml || '').match(/<t[dh][^>]*>[\s\S]*?<\/t[dh]>/gi) || [];
}

/** Accent-insensitive, colon- and case-insensitive label key. */
function normalizeLabel_(text) {
  return (text || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/:+$/, '')
    .toLowerCase();
}

/**
 * Maps every label cell to the next non-empty cell in the same row.
 * First occurrence wins, matching Python's "first matching <td>" behaviour.
 */
function buildLabelMap_(html) {
  const map = {};
  rowsOf_(html).forEach(function (row) {
    const cells = cellsOf_(row).map(cellText_).filter(function (text) {
      return text !== '';
    });
    for (let i = 0; i < cells.length - 1; i++) {
      const key = normalizeLabel_(cells[i]);
      if (key && !Object.prototype.hasOwnProperty.call(map, key)) {
        map[key] = cells[i + 1];
      }
    }
  });
  return map;
}

function labelValue_(labelMap, label) {
  const key = normalizeLabel_(label);
  return Object.prototype.hasOwnProperty.call(labelMap, key) ? labelMap[key] : '';
}

function extractCard_(labelMap) {
  for (let i = 0; i < CARD_TYPES.length; i++) {
    const value = labelValue_(labelMap, CARD_TYPES[i]);
    if (value) {
      const digits = DIGITS_RE.exec(value);
      return [CARD_TYPES[i], digits ? digits[1] : value];
    }
  }
  return ['UNKNOWN', ''];
}

function extractCardholder_(html) {
  const headings = (html || '').match(/<h[123][^>]*>[\s\S]*?<\/h[123]>/gi) || [];
  for (let i = 0; i < headings.length; i++) {
    const match = GREETING_RE.exec(cellText_(headings[i]));
    if (match) {
      return match[1].replace(/\s+/g, ' ').trim().toUpperCase();
    }
  }
  return 'UNKNOWN';
}

/**
 * "ago 12, 2026" -> "2026-08-12".
 *
 * Returns an ISO string, never a Date. Everything downstream (the Sheet, the
 * Python mirror, SQLite's TEXT date comparisons) wants a string, and a string
 * cannot be shifted by a timezone.
 */
function normalizeDate_(raw) {
  const parts = (raw || '').replace(/,/g, ' ').replace(/\s+/g, ' ').trim().split(' ');
  if (parts.length < 3) {
    throw new Error('ParseError: unrecognized date format: ' + JSON.stringify(raw));
  }

  const month = SPANISH_MONTHS[parts[0].slice(0, 3).toLowerCase()];
  if (!month) {
    throw new Error('ParseError: unrecognized Spanish month in date: ' + JSON.stringify(raw));
  }

  const day = parseInt(parts[1], 10);
  const year = parseInt(parts[2], 10);
  // Python's date(y, m, d) rejects Feb 30; building the string by hand would
  // not, so round-trip through Date.UTC to get the same validation.
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (
    isNaN(probe.getTime()) ||
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  ) {
    throw new Error('ParseError: invalid date: ' + JSON.stringify(raw));
  }

  return year + '-' + ('0' + month).slice(-2) + '-' + ('0' + day).slice(-2);
}

function parseAmount_(raw) {
  const match = AMOUNT_RE.exec(raw || '');
  if (!match) {
    throw new Error('ParseError: could not parse amount: ' + JSON.stringify(raw));
  }
  return [match[1].toUpperCase(), parseFloat(match[2].replace(/,/g, ''))];
}

/**
 * Parses one BAC notification email body into a plain transaction object,
 * plus `warnings`: the fields it could not read.
 *
 * No individual field is fatal. A transaction that reaches the Sheet with one
 * blank cell can be filled in by hand from the linked email; one that never
 * arrives is invisible, and nothing downstream can tell it apart from a month
 * you simply did not spend anything. So every field is best-effort and the
 * gaps are reported instead of thrown.
 *
 * The one hard failure is mail that is not a transaction notification at all
 * -- statements, promotions, security alerts. Those must NOT become rows.
 */
function parseTransaction_(html) {
  const labelMap = buildLabelMap_(html);

  const found = TRANSACTION_LABELS.filter(function (label) {
    return labelValue_(labelMap, label) !== '';
  });
  if (found.length < MIN_TRANSACTION_LABELS) {
    throw new Error(
      'ParseError: not a transaction notification -- found ' + found.length +
      ' of ' + TRANSACTION_LABELS.length + ' expected fields'
    );
  }

  const warnings = [];

  // Reads a labelled value and converts it, downgrading both absence and a
  // conversion failure to a warning plus `fallback`.
  function attempt_(label, fallback, convert) {
    const raw = labelValue_(labelMap, label);
    if (!raw) {
      warnings.push("missing '" + label + "'");
      return fallback;
    }
    try {
      return convert(raw);
    } catch (error) {
      warnings.push(String((error && error.message) || error).replace(/^ParseError: /, ''));
      return fallback;
    }
  }

  function verbatim_(raw) {
    return raw;
  }

  // Blank, not 0 -- an unreadable amount must not look like a free purchase.
  const amount = attempt_('Monto', ['', ''], parseAmount_);

  const card = extractCard_(labelMap);
  if (card[0] === 'UNKNOWN') {
    warnings.push('no ' + CARD_TYPES.join('/') + ' field');
  }

  return {
    reference: attempt_('Referencia', '', verbatim_),
    txnDate: attempt_('Fecha', '', normalizeDate_),
    description: labelValue_(labelMap, 'Tipo de Transaccion'),
    currency: amount[0],
    amount: amount[1],
    merchant: attempt_('Comercio', '', verbatim_),
    location: labelValue_(labelMap, 'Ciudad y pais'),
    cardType: card[0],
    lastDigits: card[1],
    cardholderName: extractCardholder_(html),
    authorization: labelValue_(labelMap, 'Autorizacion'),
    warnings: warnings,
  };
}
