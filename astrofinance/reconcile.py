import csv
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from io import StringIO

from astrofinance import repository
from astrofinance.dates import parse_date
from astrofinance.models import ReconciliationReport

FIELDS = ("reference", "amount", "date")

# Header keywords used to guess which CSV column holds each field. Matched
# against lower-cased, accent-stripped headers, so "Fecha de transacción" hits
# "fecha". Keywords are tried in order, so put the most specific first.
COLUMN_KEYWORDS = {
    "reference": ["referencia", "reference", "comprobante", "autorizacion", "authorization", "ref"],
    "amount": ["monto", "importe", "amount", "valor", "debito", "debit", "cargo"],
    "date": ["fecha de transaccion", "fecha transaccion", "fecha", "transaction date", "date"],
}

AMOUNT_TOLERANCE = 0.01
# Banks often post a charge a day or two after the notification email's date.
DATE_TOLERANCE_DAYS = 3


def _normalize_header(header: str) -> str:
    text = unicodedata.normalize("NFKD", header or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower().strip()


def guess_column_map(headers: list[str]) -> dict[str, str | None]:
    """Best-effort guess of which header holds each field. None when nothing fits."""
    normalized = {header: _normalize_header(header) for header in headers}
    result: dict[str, str | None] = {}
    taken: set[str] = set()
    for field in FIELDS:
        result[field] = None
        for keyword in COLUMN_KEYWORDS[field]:
            match = next(
                (h for h, norm in normalized.items() if h not in taken and keyword in norm), None
            )
            if match:
                result[field] = match
                taken.add(match)
                break
    return result


def read_headers(csv_text: str) -> list[str]:
    reader = csv.reader(StringIO(csv_text))
    return [header.strip() for header in next(reader, [])]


def parse_amount(raw: str | None) -> float | None:
    """Parses "1,234.56", "1.234,56", "₡12 500,00", "-45.10" or "(45.10)".

    Returns the absolute value: statements disagree on whether a charge is
    positive or negative, and the database stores charges as positive.
    """
    text = (raw or "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    text = re.sub(r"[^\d.,\-]", "", text).lstrip("-")
    if not text:
        return None

    if "," in text and "." in text:
        # Whichever separator comes last is the decimal one.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # A lone comma followed by one or two digits is a decimal comma;
        # otherwise it is a thousands separator.
        text = text.replace(",", ".") if re.search(r",\d{1,2}$", text) else text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def _find_by_amount_and_date(
    conn: sqlite3.Connection, amount: float, row_date: date, exclude_ids: set[int]
) -> sqlite3.Row | None:
    """Closest-dated unmatched transaction with the same amount, within tolerance."""
    window_start = (row_date - timedelta(days=DATE_TOLERANCE_DAYS)).isoformat()
    window_end = (row_date + timedelta(days=DATE_TOLERANCE_DAYS)).isoformat()
    candidates = conn.execute(
        f"""{repository.TRANSACTION_SELECT}
        WHERE t.txn_date BETWEEN ? AND ? AND ABS(ABS(t.amount) - ?) < ?
        ORDER BY ABS(julianday(t.txn_date) - julianday(?)), t.id""",
        (window_start, window_end, amount, AMOUNT_TOLERANCE, row_date.isoformat()),
    ).fetchall()
    return next((txn for txn in candidates if txn["id"] not in exclude_ids), None)


def reconcile(
    conn: sqlite3.Connection,
    csv_text: str,
    column_map: dict[str, str | None] | None = None,
) -> ReconciliationReport:
    """Match statement rows against stored transactions, by reference then amount+date.

    Each transaction matches at most one statement row. "Missing in statement"
    only covers the date range the statement spans, so older history does not
    show up as missing.
    """
    report = ReconciliationReport()
    reader = csv.DictReader(StringIO(csv_text))
    if reader.fieldnames:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
    column_map = column_map or guess_column_map(list(reader.fieldnames or []))
    report.column_map = dict(column_map)

    def cell(row: dict, field: str) -> str:
        column = column_map.get(field)
        return (row.get(column) or "").strip() if column else ""

    matched_ids: set[int] = set()
    statement_dates: list[date] = []

    for row in reader:
        if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
            continue  # blank line

        reference = cell(row, "reference")
        amount = parse_amount(cell(row, "amount"))
        row_date = parse_date(cell(row, "date"))
        if row_date:
            statement_dates.append(row_date)

        txn = repository.find_transaction_by_reference(conn, reference) if reference else None
        if txn is not None and txn["id"] in matched_ids:
            report.mismatched.append(
                {"csv_row": row, "transaction": dict(txn), "reason": "reference appears more than once in the statement"}
            )
            continue
        if txn is None and amount is not None and row_date is not None:
            txn = _find_by_amount_and_date(conn, amount, row_date, matched_ids)

        if txn is None:
            report.missing_in_db.append(row)
            continue

        matched_ids.add(txn["id"])
        entry = {"csv_row": row, "transaction": dict(txn)}
        if amount is not None and abs(abs(txn["amount"]) - amount) >= AMOUNT_TOLERANCE:
            entry["reason"] = f"amount differs: db {txn['amount']} vs statement {amount}"
            report.mismatched.append(entry)
        else:
            report.matched.append(entry)

    if statement_dates:
        report.period = (min(statement_dates), max(statement_dates))
        rows, _ = repository.list_transactions(conn, *report.period)
        report.missing_in_statement = [dict(row) for row in rows if row["id"] not in matched_ids]
    return report
