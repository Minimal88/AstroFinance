/**
 * Parser tests, ported from tests/test_parser.py.
 *
 * Started as the assertions that guarded the Python parser before Apps Script
 * took over ingestion, and grew the degradation cases that real BAC mail
 * turned up. Run runParserTests() from the editor and read the log; every
 * line should start with PASS.
 *
 * These two functions deliberately have NO trailing underscore: Apps Script
 * treats a trailing underscore as "private" and hides such functions from the
 * editor's Run dropdown.
 */

const SAMPLE_EMAIL = [
  '<html><body>',
  '  <h2>Hola  Esteban  Martinez Valverde</h2>',
  '  <p>Le informamos de la siguiente transaccion:</p>',
  '  <table>',
  '    <tr><td>Comercio:</td><td>AMAZON MKTPL</td></tr>',
  '    <tr><td>Ciudad y pa&iacute;s:</td><td>SEATTLE, US</td></tr>',
  '    <tr><td>Fecha:</td><td>ago 12, 2026</td></tr>',
  '    <tr><td>Tipo de Transacci&oacute;n:</td><td>COMPRA</td></tr>',
  '    <tr><td>Monto:</td><td>USD 45.30</td></tr>',
  '    <tr><td>VISA:</td><td>************4821</td></tr>',
  '    <tr><td>Autorizaci&oacute;n:</td><td>091234</td></tr>',
  '    <tr><td>Referencia:</td><td>987654321012</td></tr>',
  '  </table>',
  '</body></html>',
].join('\n');

// Mail from the same sender that is NOT a transaction. Its labels are close
// cousins of the real ones -- "Fecha de corte", not "Fecha" -- which is exactly
// the case the transaction-notification test has to reject.
const STATEMENT_EMAIL = [
  '<html><body>',
  '  <h2>Hola Esteban Martinez Valverde</h2>',
  '  <table>',
  '    <tr><td>Fecha de corte:</td><td>ago 12, 2026</td></tr>',
  '    <tr><td>Monto a pagar:</td><td>CRC 250,000.00</td></tr>',
  '  </table>',
  '</body></html>',
].join('\n');

function runParserTests() {
  const results = [];

  function check(name, actual, expected) {
    const ok = String(actual) === String(expected);
    results.push((ok ? 'PASS' : 'FAIL') + ' ' + name +
      (ok ? '' : ' -- expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(actual)));
  }

  function checkThrows(name, fn) {
    let threw = false;
    try {
      fn();
    } catch (e) {
      threw = String(e.message || e).indexOf('ParseError') >= 0;
    }
    results.push((threw ? 'PASS' : 'FAIL') + ' ' + name + (threw ? '' : ' -- expected a ParseError'));
  }

  const parsed = parseTransaction_(SAMPLE_EMAIL);

  // test_extracts_core_fields
  check('reference', parsed.reference, '987654321012');
  check('merchant', parsed.merchant, 'AMAZON MKTPL');
  check('description', parsed.description, 'COMPRA');
  check('location', parsed.location, 'SEATTLE, US');
  check('authorization', parsed.authorization, '091234');

  // test_extracts_card_and_cardholder
  check('cardType', parsed.cardType, 'VISA');
  check('lastDigits', parsed.lastDigits, '4821');
  check('cardholderName', parsed.cardholderName, 'ESTEBAN MARTINEZ VALVERDE');

  // test_extracts_amount_and_date
  check('currency', parsed.currency, 'USD');
  check('amount', parsed.amount, 45.3);
  check('txnDate', parsed.txnDate, '2026-08-12');
  check('clean email warns about nothing', parsed.warnings.length, 0);

  // test_unknown_card_type_falls_back
  const unknownCard = parseTransaction_(SAMPLE_EMAIL.replace('VISA:', 'DISCOVER:'));
  check('unknown card type', unknownCard.cardType, 'UNKNOWN');
  check('unknown card digits', unknownCard.lastDigits, '');
  check('unknown card warns', unknownCard.warnings.join('; '), 'no VISA/MASTER/AMEX field');

  // test_missing_greeting_yields_unknown_cardholder
  const noGreeting = parseTransaction_(
    SAMPLE_EMAIL.replace('<h2>Hola  Esteban  Martinez Valverde</h2>', '')
  );
  check('missing greeting', noGreeting.cardholderName, 'UNKNOWN');

  // A missing field must never cost the whole transaction. This replaces
  // test_missing_reference_raises, which asserted the opposite: BAC really does
  // send purchase notifications with no Referencia (GASOLINERA SKY 7,
  // CAFE BOHIO, HOLA INDIA -- all dropped before this changed).
  const noReference = parseTransaction_(SAMPLE_EMAIL.replace('Referencia:', 'Otro:'));
  check('missing reference warns', noReference.warnings.join('; '), "missing 'Referencia'");
  check('missing reference leaves it blank', noReference.reference, '');
  check('missing reference keeps merchant', noReference.merchant, 'AMAZON MKTPL');
  check('missing reference keeps amount', noReference.amount, 45.3);
  check('missing reference keeps date', noReference.txnDate, '2026-08-12');

  // Same rule for a field that is present but unreadable.
  const badDate = parseTransaction_(SAMPLE_EMAIL.replace('ago 12, 2026', 'xyz 12, 2026'));
  check('bad date blanks the date', badDate.txnDate, '');
  check('bad date warns', badDate.warnings.length, 1);
  check('bad date keeps merchant', badDate.merchant, 'AMAZON MKTPL');

  // Blank, not 0 -- an unreadable amount must not look like a free purchase.
  const badAmount = parseTransaction_(SAMPLE_EMAIL.replace('USD 45.30', 'importe no disponible'));
  check('bad amount blanks the amount', badAmount.amount, '');
  check('bad amount blanks the currency', badAmount.currency, '');
  check('bad amount keeps merchant', badAmount.merchant, 'AMAZON MKTPL');

  // referenceFor_ is what makes a referenceless transaction storable and still
  // dedupable: same email in, same key out, on every run.
  const fakeMessage = { getId: function () { return '1a001c125b1ebf4a'; } };
  check('stand-in key from the message id',
    referenceFor_(noReference, fakeMessage), 'GM-1a001c125b1ebf4a');
  check("BAC's own reference wins", referenceFor_(parsed, fakeMessage), '987654321012');

  // The one hard failure: mail that is not a transaction must not become a row.
  checkThrows('statement is not a transaction', function () {
    parseTransaction_(STATEMENT_EMAIL);
  });
  checkThrows('empty body is not a transaction', function () {
    parseTransaction_('<html><body><p>Nada</p></body></html>');
  });

  // test_amount_strips_thousands_separator
  const bigAmount = parseAmount_('CRC 1,234,567.89');
  check('thousands separator currency', bigAmount[0], 'CRC');
  check('thousands separator amount', bigAmount[1], 1234567.89);

  // test_unparseable_amount_raises
  checkThrows('unparseable amount raises', function () {
    parseAmount_('no amount here');
  });

  // test_spanish_month_dates
  check('date ago', normalizeDate_('ago 12, 2026'), '2026-08-12');
  check('date ene', normalizeDate_('ene 1, 2026'), '2026-01-01');
  check('date dic', normalizeDate_('dic 31, 2025'), '2025-12-31');

  // test_unknown_month_raises
  checkThrows('unknown month raises', function () {
    normalizeDate_('xyz 12, 2026');
  });

  // Not in the Python suite: JS string building would happily accept Feb 30,
  // so the Date.UTC round-trip guard needs its own check.
  checkThrows('invalid calendar date raises', function () {
    normalizeDate_('feb 30, 2026');
  });

  const failed = results.filter(function (line) {
    return line.indexOf('FAIL') === 0;
  }).length;

  Logger.log(results.join('\n'));
  Logger.log(failed === 0 ? 'ALL ' + results.length + ' ASSERTIONS PASSED' : failed + ' ASSERTION(S) FAILED');
}

/**
 * Prints the parsed output of the most recent matching email, for eyeballing
 * against astrofinance/parser.py during the port verification (the "oracle
 * diff" step). Safe: reads only, writes nothing.
 */
function debugParseLatest() {
  const threads = GmailApp.search('from:' + senderEmail_(), 0, 1);
  if (threads.length === 0) {
    Logger.log('No messages found for that sender.');
    return;
  }
  const messages = threads[0].getMessages();
  const message = messages[messages.length - 1];
  Logger.log('Subject: ' + message.getSubject());
  Logger.log(JSON.stringify(parseTransaction_(message.getBody()), null, 2));
}
