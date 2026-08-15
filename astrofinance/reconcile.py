import csv
import sqlite3
from io import StringIO

from astrofinance import repository
from astrofinance.dates import parse_date
from astrofinance.models import ReconciliationReport

# TODO: replace with the real BAC export column headers once a sample CSV is available.
CSV_COLUMN_MAP = {
    "reference": "TODO_REFERENCE_COLUMN",
    "amount": "TODO_AMOUNT_COLUMN",
    "date": "TODO_DATE_COLUMN",
}

AMOUNT_TOLERANCE = 0.01


def _parse_amount(raw: str) -> float | None:
    cleaned = (raw or "").replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def reconcile(conn: sqlite3.Connection, csv_text: str) -> ReconciliationReport:
    """Match statement rows against stored transactions, by reference then amount+date."""
    report = ReconciliationReport()
    reader = csv.DictReader(StringIO(csv_text))
    seen_transaction_ids: set[int] = set()

    for row in reader:
        reference = (row.get(CSV_COLUMN_MAP["reference"]) or "").strip()
        amount = _parse_amount(row.get(CSV_COLUMN_MAP["amount"], ""))
        row_date = parse_date(row.get(CSV_COLUMN_MAP["date"], ""))

        txn = repository.find_transaction_by_reference(conn, reference) if reference else None
        if txn is None and amount is not None and row_date is not None:
            txn = conn.execute(
                f"{repository.TRANSACTION_SELECT} WHERE t.txn_date = ? AND ABS(t.amount - ?) < ?",
                (row_date.isoformat(), amount, AMOUNT_TOLERANCE),
            ).fetchone()

        if txn is None:
            report.missing_in_db.append(row)
            continue

        seen_transaction_ids.add(txn["id"])
        entry = {"csv_row": row, "transaction": dict(txn)}
        if amount is not None and abs(txn["amount"] - amount) >= AMOUNT_TOLERANCE:
            entry["reason"] = f"amount differs: db {txn['amount']} vs statement {amount}"
            report.mismatched.append(entry)
        else:
            report.matched.append(entry)

    rows, _ = repository.list_transactions(conn)
    report.missing_in_statement = [dict(row) for row in rows if row["id"] not in seen_transaction_ids]
    return report
