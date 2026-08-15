/**
 * Setup diagnostics. Read-only: these never write to the Sheet.
 *
 * No trailing underscore on the entry points -- Apps Script hides underscored
 * functions from the Run dropdown.
 */

/** Pulls the bare address out of a "Display Name <addr@host>" From header. */
function addressOf_(fromHeader) {
  const angled = String(fromHeader || '').match(/<([^>]+)>/);
  return (angled ? angled[1] : String(fromHeader || '')).trim().toLowerCase();
}

/**
 * Best-effort "which mailbox am I reading?".
 *
 * Session.getActiveUser().getEmail() returns '' here because appsscript.json
 * pins its scopes and userinfo.email is not one of them -- adding it would
 * force everyone to re-authorize just to power a diagnostic. The To: header of
 * any recent message answers the same question under gmail.readonly, which the
 * script already holds.
 */
function activeMailbox_() {
  try {
    const email = Session.getActiveUser().getEmail();
    if (email) return email;
  } catch (e) {
    // Scope not granted; fall through to the header probe.
  }
  try {
    const threads = GmailApp.search('in:anywhere', 0, 1);
    if (threads.length === 0) return '(mailbox is empty)';
    const messages = threads[0].getMessages();
    return addressOf_(messages[0].getTo()) + ' (inferred from a To: header)';
  } catch (e) {
    return '(unknown: ' + (e.message || e) + ')';
  }
}

/**
 * Answers "why did the search find nothing?" by showing what is actually
 * configured and which query shapes do match.
 *
 * Note GmailApp.search() excludes Spam and Trash unless the query says
 * in:anywhere -- a bank notification filtered to Spam is invisible to the
 * normal query, so that variant is tested explicitly.
 */
function diagnoseSender() {
  const raw = props_().getProperty('BAC_SENDER_EMAIL');
  const sender = senderEmail_();
  const domain = sender.indexOf('@') >= 0 ? sender.split('@')[1] : sender;

  const out = [];
  out.push('Reading mailbox: ' + activeMailbox_());
  // JSON.stringify so trailing spaces and newlines are visible.
  out.push('Property (raw):  ' + JSON.stringify(raw));
  out.push('Used in query:   ' + JSON.stringify(sender));
  out.push('');

  const queries = [
    'from:' + sender,
    'in:anywhere from:' + sender,
    'from:' + domain,
    'in:anywhere from:' + domain,
  ];

  queries.forEach(function (query) {
    let count;
    try {
      count = GmailApp.search(query, 0, 50).length;
    } catch (e) {
      count = 'ERROR: ' + (e.message || e);
    }
    out.push(String(count) + '\tthread(s)\t' + query);
  });

  out.push('');
  out.push('0 everywhere means the address is wrong -- run listBacSenders().');
  out.push('0 on the first query but not the second means the mail is in');
  out.push('Spam or Trash; fix that in Gmail rather than changing the query.');
  Logger.log(out.join('\n'));
}

/**
 * Walks every message matching a query, paging until exhausted or out of time,
 * calling visit(message) on each. Returns { threads, messages, truncated }.
 */
function scanMessages_(query, deadline, visit) {
  let offset = 0;
  let threads = 0;
  let messages = 0;

  while (true) {
    if (Date.now() > deadline) {
      return { threads: threads, messages: messages, truncated: true };
    }

    const page = GmailApp.search(query, offset, BACKFILL_PAGE_SIZE);
    if (page.length === 0) {
      return { threads: threads, messages: messages, truncated: false };
    }

    for (let t = 0; t < page.length; t++) {
      const inThread = page[t].getMessages();
      threads += 1;
      for (let m = 0; m < inThread.length; m++) {
        messages += 1;
        visit(inThread[m]);
      }
    }
    offset += page.length;
  }
}

/**
 * A day offset from BACKFILL_BEFORE (yyyy/MM/dd), as yyyy-MM-dd so it can be
 * string-compared against a formatted message date. '' when unset.
 */
function cutoffDay_(cutoffRaw, offsetDays) {
  if (!cutoffRaw) return '';
  const parts = String(cutoffRaw).split('/');
  const day = new Date(Date.UTC(
    Number(parts[0]),
    Number(parts[1]) - 1,
    Number(parts[2]) + offsetDays
  ));
  // Built at UTC midnight, so the ISO prefix is exactly the calendar day.
  return day.toISOString().slice(0, 10);
}

/** Whether the recurring incremental sync is actually installed. */
function triggerInstalled_() {
  return ScriptApp.getProjectTriggers().some(function (trigger) {
    return trigger.getHandlerFunction() === 'runIncrementalSync';
  });
}

/**
 * How far back the incremental sync currently reaches, as yyyy-MM-dd.
 *
 * Derived from INCREMENTAL_WINDOW rather than hard-coded, so the audit cannot
 * drift from what runIncrementalSync() actually queries. Anything older than
 * this is out of the sync's reach no matter how many times it runs -- that
 * needs a backfill, and saying "the trigger will get it" would be false.
 */
function syncHorizon_() {
  const days = Number((INCREMENTAL_WINDOW.match(/(\d+)d/) || [])[1] || 0);
  const day = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  return Utilities.formatDate(day, 'America/Costa_Rica', 'yyyy-MM-dd');
}

/**
 * The coverage invariant: every message from the sender must be accounted for.
 * It either produced a Transactions row, or it is logged in ParseErrors, or it
 * repeats a Reference that is already stored. Anything else is a real gap.
 *
 * Counting rows against Gmail's result count does NOT test this. Gmail counts
 * THREADS and the Sheet stores one row per MESSAGE, and BAC reuses subject
 * lines so one thread routinely holds many transactions. This compares Gmail
 * message IDs against the Sheet instead, which is exact, and it re-parses
 * anything unaccounted for so each gap comes with a reason.
 *
 * Read-only. Run it after a backfill and any time the numbers look wrong.
 */
function auditCoverage() {
  const sender = senderEmail_();
  const deadline = Date.now() + MAX_RUNTIME_MS;

  const storedIds = columnSet_('Transactions', 'GmailMessageId');
  const storedRefs = columnSet_('Transactions', 'Reference');
  const loggedIds = columnSet_('ParseErrors', 'GmailMessageId');

  // What ingestion can actually reach: GmailApp.search() skips Spam and Trash
  // unless the query says in:anywhere. The census below deliberately uses
  // in:anywhere, so this set is what separates "we missed it" from "the query
  // cannot see it".
  const reachable = new Set();
  const reach = scanMessages_('from:' + sender, deadline, function (message) {
    reachable.add(message.getId());
  });

  // Mail on or after this date was never in scope for the backfill; the
  // incremental sync owns it. Stored as yyyy/MM/dd for Gmail's before:. This is
  // bookkeeping for one paged backfill, not a limit on how far the Sheet goes.
  //
  // That boundary is a day wide, not a point. Gmail resolves before: against a
  // timezone of its own, so an email late on the day BEFORE the cutoff can also
  // land outside the query -- and this audit stamps dates in America/Costa_Rica,
  // which is UTC-6, so any evening transaction is already the next day in UTC.
  // Flagging only `date >= cutoff` reports those as unexplained gaps.
  const cutoffRaw = props_().getProperty('BACKFILL_BEFORE');
  const cutoff = cutoffDay_(cutoffRaw, 0);
  const cutoffEve = cutoffDay_(cutoffRaw, -1);

  // Whether that explanation is worth anything: an uninstalled trigger sweeps
  // up nothing, and neither does an installed one for mail older than its
  // window. Both are stated rather than assumed.
  const syncing = triggerInstalled_();
  const horizon = syncHorizon_();

  const unaccounted = [];
  let inSheet = 0;
  let withGaps = 0;
  let inErrors = 0;

  const census = scanMessages_('in:anywhere from:' + sender, deadline, function (message) {
    const id = message.getId();
    if (storedIds.has(id)) {
      inSheet += 1;
      // Stored AND logged: a transaction with blank cells. Both tabs is
      // correct here, so this is counted rather than treated as a conflict.
      if (loggedIds.has(id)) withGaps += 1;
      return;
    }
    if (loggedIds.has(id)) {
      inErrors += 1;
      return;
    }

    const date = Utilities.formatDate(message.getDate(), 'America/Costa_Rica', 'yyyy-MM-dd');
    let verdict;
    try {
      const parsed = parseTransaction_(message.getBody());
      const reference = referenceFor_(parsed, message);
      verdict = storedRefs.has(reference)
        ? 'DUPLICATE  reference ' + reference + ' is already stored'
        : 'MISSING    parses fine, reference ' + reference + ' is not in the Sheet';
    } catch (error) {
      verdict = 'NOT A TXN  ' + (error.message || error);
    }

    const notes = [];
    if (!reachable.has(id)) notes.push('in Spam or Trash, so ingestion cannot see it');
    // Only MISSING is waiting on something. A DUPLICATE was skipped on purpose
    // and a NOT A TXN was never going to be a row, so telling either of them
    // how to get ingested reads as an action item that does not exist.
    if (verdict.indexOf('MISSING') === 0 && cutoffEve && date >= cutoffEve) {
      notes.push(
        (date >= cutoff
          ? 'arrived after backfillStart() pinned the backfill at ' + cutoff
          : 'on the ' + cutoff + ' backfill boundary, which is a day wide') +
        (!syncing
          ? '; nothing is syncing it in -- run installTrigger()'
          : date >= horizon
            ? '; inside the ' + INCREMENTAL_WINDOW + ' sync window, so the next run picks it up'
            : '; but older than the ' + INCREMENTAL_WINDOW + ' sync window (' + horizon +
              ') -- only a backfill reaches it now')
      );
    }

    unaccounted.push(
      date + '  ' + verdict +
      '\n           ' + message.getSubject() +
      (notes.length ? '\n           (' + notes.join('; ') + ')' : '') +
      '\n           ' + permalinkFor_(message)
    );
  });

  const out = [];
  out.push('Coverage audit for from:' + sender);
  out.push(syncing
    ? 'Incremental sync: every ' + TRIGGER_INTERVAL_MINUTES + ' min, ' +
      INCREMENTAL_WINDOW + ' lookback (back to ' + horizon + ').'
    : 'Incremental sync: NOT INSTALLED. Nothing new is arriving -- run installTrigger().');
  out.push('');
  out.push(census.threads + ' thread(s) hold ' + census.messages + ' message(s).');
  out.push("Gmail's result count is THREADS; the Sheet stores one row per MESSAGE.");
  out.push('Those two numbers are not supposed to match.');
  out.push('');
  out.push(inSheet + '\tin Transactions' +
    (withGaps > 0 ? ' (' + withGaps + ' with blank fields, also listed in ParseErrors)' : ''));
  out.push(inErrors + '\tin ParseErrors only -- not transaction notifications');
  out.push(unaccounted.length + '\tunaccounted for');

  if (reach.truncated || census.truncated) {
    out.push('');
    out.push('WARNING: ran out of time mid-scan, so these counts are partial.');
  }

  if (unaccounted.length === 0) {
    out.push('');
    out.push('Every message is accounted for.');
  } else {
    out.push('');
    out.push(unaccounted.join('\n'));
    out.push('');
    out.push('DUPLICATE  BAC sent the same transaction twice. Skipped on purpose,');
    out.push('           no action needed.');
    out.push('NOT A TXN  A statement, promotion or alert -- correctly not a row.');
    out.push('           Never scanned, though: had it been, it would be in');
    out.push('           ParseErrors. If the subject looks like a purchase, the BAC');
    out.push('           template changed and Parser.gs needs a look.');
    out.push('MISSING    Parses fine but is not in the Sheet.');
    out.push('');
    out.push('A note in parentheses names the cause and says what closes it.');
    out.push('Anything about the backfill boundary is normal: the backfill stops at');
    out.push('the day it was armed, and the ' + TRIGGER_INTERVAL_MINUTES +
      '-minute sync owns everything newer.');
    out.push('  Spam/Trash  -> fix it in Gmail. GmailApp.search() reaches neither,');
    out.push('                 so no amount of re-running the backfill will help.');
    out.push('');
    out.push('NOT A TXN or MISSING with NO note is a real gap: re-run backfillReset(),');
    out.push('backfillStart(), backfillRun() -- re-ingesting is free because dedup is');
    out.push('by Reference.');
  }

  Logger.log(out.join('\n'));
}

/**
 * Finds candidate BAC addresses by tallying the From headers of anything that
 * looks like a bank notification. Use this to get the exact address for
 * BAC_SENDER_EMAIL instead of eyeballing one email.
 */
function listBacSenders() {
  const probes = [
    'in:anywhere bac',
    'in:anywhere credomatic',
    'in:anywhere subject:(compra OR transaccion OR transacción)',
    'in:anywhere "Referencia"',
  ];

  const tally = {};
  const samples = {};
  let scanned = 0;

  probes.forEach(function (query) {
    let threads = [];
    try {
      threads = GmailApp.search(query, 0, 20);
    } catch (e) {
      return;
    }
    threads.forEach(function (thread) {
      const messages = thread.getMessages();
      // One message is enough per thread here: this is a census of senders,
      // not ingestion, so the full-thread rule does not apply.
      const message = messages[messages.length - 1];
      const address = addressOf_(message.getFrom());
      if (!address) return;
      scanned += 1;
      tally[address] = (tally[address] || 0) + 1;
      if (!samples[address]) samples[address] = message.getSubject();
    });
  });

  const ranked = Object.keys(tally).sort(function (a, b) {
    return tally[b] - tally[a];
  });

  if (ranked.length === 0) {
    Logger.log(
      'No candidate senders found. Either this account holds no BAC mail, or\n' +
      'the script is authorized as a different account than you expect --\n' +
      'check the "Reading mailbox" line from diagnoseSender().'
    );
    return;
  }

  const out = ['Scanned ' + scanned + ' thread(s). Candidate senders, most frequent first:', ''];
  ranked.forEach(function (address) {
    out.push(tally[address] + '\t' + address);
    out.push('\t\te.g. "' + samples[address] + '"');
  });
  out.push('');
  out.push('Copy the address whose subject looks like a card notification into');
  out.push('Script Properties -> BAC_SENDER_EMAIL, then re-run diagnoseSender().');
  Logger.log(out.join('\n'));
}
