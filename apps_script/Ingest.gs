/**
 * Gmail -> Sheet ingestion.
 *
 * Two entry points:
 *   runIncrementalSync()  the trigger target; a short rolling window
 *   backfillRun()         one-time history load, run manually until COMPLETE
 *
 * Dedup is by Reference against what is already in the Sheet, which is why no
 * Gmail label bookkeeping is needed and why re-processing an email is free.
 */

/**
 * Processes one page of threads into row arrays.
 * Returns { rows, errorRows, duplicates, rejected, incomplete, messagesSeen,
 * stoppedEarly }.
 *
 * Two invariants hold, and the run log prints the first:
 *   messagesSeen == rows + duplicates + rejected
 *   errorRows    == rejected + incomplete
 *
 * Every message lands in exactly one of stored / duplicate / rejected, so a
 * smaller-than-expected row count always has a stated reason. `incomplete`
 * overlaps `rows` on purpose: a transaction with a blank field is stored AND
 * logged, never dropped.
 */
function collectRows_(threads, knownRefs, deadline, budget) {
  const rows = [];
  const errorRows = [];
  let duplicates = 0;
  let rejected = 0;
  let incomplete = 0;
  let messagesSeen = 0;
  let stoppedEarly = false;

  function result_() {
    return {
      rows: rows,
      errorRows: errorRows,
      duplicates: duplicates,
      rejected: rejected,
      incomplete: incomplete,
      messagesSeen: messagesSeen,
      stoppedEarly: stoppedEarly,
    };
  }

  for (let t = 0; t < threads.length; t++) {
    // BAC reuses subject lines, so Gmail groups many transactions into one
    // thread. Every message must be visited -- taking messages[0] would
    // silently drop most transactions.
    const messages = threads[t].getMessages();

    for (let m = 0; m < messages.length; m++) {
      if (Date.now() > deadline || messagesSeen >= budget) {
        stoppedEarly = true;
        return result_();
      }

      const message = messages[m];
      messagesSeen++;

      let parsed;
      try {
        parsed = parseTransaction_(message.getBody());
      } catch (error) {
        // Not a transaction notification at all. This is the ONLY reason a
        // message fails to produce a row; a missing field never is.
        rejected++;
        errorRows.push(toErrorRow_(message, error));
        continue;
      }

      const reference = referenceFor_(parsed, message);

      // Already stored, either by an earlier run or because BAC sent the same
      // transaction twice. Both are correct skips; auditCoverage() can tell
      // them apart after the fact.
      if (knownRefs.has(reference)) {
        duplicates++;
        continue;
      }
      knownRefs.add(reference);
      rows.push(toTransactionRow_(parsed, message));

      // Stored, but with blank cells. Logged as well so ParseErrors stays the
      // complete list of things needing a human look.
      if (parsed.warnings.length > 0) {
        incomplete++;
        errorRows.push(toWarningRow_(message, reference, parsed.warnings));
      }
    }
  }

  return result_();
}

/**
 * "47 messages scanned = 41 new + 5 already stored + 1 not a transaction."
 *
 * Deliberately never reports thread counts as though they were row counts: one
 * thread can hold many transactions, so comparing Gmail's result count against
 * the Sheet's row count is meaningless.
 */
function tallyLine_(counts) {
  return (
    counts.scanned + ' messages scanned = ' +
    counts.added + ' new + ' +
    counts.duplicates + ' already stored + ' +
    counts.rejected + ' not a transaction' +
    (counts.incomplete > 0
      ? '\n' + counts.incomplete + ' of the new rows ' +
        (counts.incomplete === 1 ? 'has' : 'have') +
        ' blank fields -- stored anyway, listed in ParseErrors.'
      : '')
  );
}

/** Trigger target. Scans a short rolling window and appends anything new. */
function runIncrementalSync() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    Logger.log('Another run holds the lock; skipping.');
    return;
  }

  try {
    const deadline = Date.now() + MAX_RUNTIME_MS;
    const query = 'from:' + senderEmail_() + ' ' + INCREMENTAL_WINDOW;
    const threads = GmailApp.search(query, 0, 100);
    const knownRefs = loadReferenceSet_();

    const result = collectRows_(threads, knownRefs, deadline, MAX_MESSAGES_PER_RUN);
    appendRows_('Transactions', result.rows);
    appendRows_('ParseErrors', result.errorRows);

    Logger.log(
      'Incremental sync: ' + tallyLine_({
        scanned: result.messagesSeen,
        added: result.rows.length,
        duplicates: result.duplicates,
        rejected: result.rejected,
        incomplete: result.incomplete,
      }) +
      (result.stoppedEarly ? ' (stopped early on budget)' : '')
    );
  } finally {
    lock.releaseLock();
  }
}

/**
 * Starts a one-time backfill of the full history.
 *
 * `before:` is pinned at the start date so paging stays deterministic while
 * new mail keeps arriving; the incremental trigger covers anything newer.
 */
function backfillStart() {
  const today = Utilities.formatDate(new Date(), 'America/Costa_Rica', 'yyyy/MM/dd');
  props_().setProperties({
    BACKFILL_BEFORE: today,
    BACKFILL_OFFSET: '0',
    BACKFILL_ACTIVE: 'true',
  });
  Logger.log('Backfill armed for mail before ' + today + '. Now run backfillRun() until it logs COMPLETE.');
}

/**
 * Processes one chunk of the backfill. Run this MANUALLY from the editor,
 * repeatedly, until it logs COMPLETE -- manual executions do not draw on the
 * 90 min/day trigger runtime quota, so the whole backfill is free.
 *
 * Do not install the incremental trigger until this reports COMPLETE.
 */
function backfillRun() {
  if (props_().getProperty('BACKFILL_ACTIVE') !== 'true') {
    Logger.log('Backfill is not active. Run backfillStart() first.');
    return;
  }

  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    Logger.log('Another run holds the lock; skipping.');
    return;
  }

  try {
    const deadline = Date.now() + MAX_RUNTIME_MS;
    const query = 'from:' + senderEmail_() + ' before:' + requireProperty_('BACKFILL_BEFORE');
    const knownRefs = loadReferenceSet_();

    let offset = parseInt(props_().getProperty('BACKFILL_OFFSET') || '0', 10);
    const counts = { scanned: 0, added: 0, duplicates: 0, rejected: 0, incomplete: 0 };

    while (Date.now() < deadline) {
      const threads = GmailApp.search(query, offset, BACKFILL_PAGE_SIZE);
      if (threads.length === 0) {
        props_().setProperty('BACKFILL_ACTIVE', 'false');
        Logger.log(
          'BACKFILL COMPLETE over ' + offset + ' threads.\n' +
          'This run: ' + tallyLine_(counts) + '\n' +
          'Run auditCoverage() to confirm every email is accounted for, then installTrigger().'
        );
        return;
      }

      const result = collectRows_(threads, knownRefs, deadline, Number.MAX_SAFE_INTEGER);
      counts.added += appendRows_('Transactions', result.rows);
      appendRows_('ParseErrors', result.errorRows);
      counts.scanned += result.messagesSeen;
      counts.duplicates += result.duplicates;
      counts.rejected += result.rejected;
      counts.incomplete += result.incomplete;

      if (result.stoppedEarly) break;

      offset += threads.length;
      props_().setProperty('BACKFILL_OFFSET', String(offset));
    }

    Logger.log(
      'Backfill chunk done: ' + tallyLine_(counts) + '\nOffset now ' + offset +
      ' threads. Run backfillRun() again.'
    );
  } finally {
    lock.releaseLock();
  }
}

function backfillStatus() {
  const p = props_().getProperties();
  Logger.log(
    'active=' + (p.BACKFILL_ACTIVE || 'false') +
    ' offset=' + (p.BACKFILL_OFFSET || '0') +
    ' before=' + (p.BACKFILL_BEFORE || '(unset)')
  );
}

function backfillReset() {
  props_().deleteProperty('BACKFILL_ACTIVE');
  props_().deleteProperty('BACKFILL_OFFSET');
  props_().deleteProperty('BACKFILL_BEFORE');
  Logger.log('Backfill state cleared.');
}

/** Installs (or reinstalls) the recurring trigger. */
function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'runIncrementalSync') {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger('runIncrementalSync')
    .timeBased()
    .everyMinutes(TRIGGER_INTERVAL_MINUTES)
    .create();

  Logger.log('Trigger installed: runIncrementalSync every ' + TRIGGER_INTERVAL_MINUTES + ' minutes.');
}

function removeTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'runIncrementalSync') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  Logger.log('Trigger removed.');
}
