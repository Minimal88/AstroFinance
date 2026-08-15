import sqlite3
from datetime import date

TRANSACTION_SELECT = """
    SELECT t.*, ch.name AS cardholder_name, c.card_type, c.last_digits
    FROM transactions t
    JOIN cardholders ch ON ch.id = t.cardholder_id
    JOIN cards c ON c.id = t.card_id
"""


def get_or_create_cardholder(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM cardholders WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute("INSERT INTO cardholders (name) VALUES (?)", (name,))
    return cursor.lastrowid


def get_or_create_card(conn: sqlite3.Connection, cardholder_id: int, card_type: str, last_digits: str) -> int:
    row = conn.execute(
        "SELECT id FROM cards WHERE card_type = ? AND last_digits = ?", (card_type, last_digits)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO cards (cardholder_id, card_type, last_digits) VALUES (?, ?, ?)",
        (cardholder_id, card_type, last_digits),
    )
    return cursor.lastrowid


def upsert_payment(
    conn: sqlite3.Connection,
    payment_id: str,
    payment_date: date,
    amount: float,
    currency: str | None,
    notes: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO payments (id, payment_date, amount, currency, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            payment_date = excluded.payment_date,
            amount       = excluded.amount,
            currency     = excluded.currency,
            notes        = excluded.notes
        """,
        (payment_id, payment_date.isoformat(), amount, currency, notes),
    )


def upsert_transaction(
    conn: sqlite3.Connection,
    reference: str,
    txn_date: date,
    description: str,
    currency: str,
    amount: float,
    merchant: str,
    location: str,
    card_id: int,
    cardholder_id: int,
    authorization: str,
    category: str | None = None,
    gmail_message_id: str | None = None,
    gmail_permalink: str | None = None,
    payment_id: str | None = None,
) -> None:
    """Inserts or updates by reference.

    This must update rather than ignore on conflict: updating `payment_id` and
    `category` is how a payment marked on the phone reaches the local mirror.

    Note it cannot report whether the row was new -- SQLite sets rowcount to 1
    for both branches of an upsert. Callers compare against
    existing_references() instead.
    """
    conn.execute(
        """
        INSERT INTO transactions (
            reference, txn_date, description, currency, amount, merchant, location,
            card_id, cardholder_id, authorization, category, gmail_message_id,
            gmail_permalink, payment_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(reference) DO UPDATE SET
            txn_date         = excluded.txn_date,
            description      = excluded.description,
            currency         = excluded.currency,
            amount           = excluded.amount,
            merchant         = excluded.merchant,
            location         = excluded.location,
            card_id          = excluded.card_id,
            cardholder_id    = excluded.cardholder_id,
            authorization    = excluded.authorization,
            category         = excluded.category,
            gmail_message_id = excluded.gmail_message_id,
            gmail_permalink  = excluded.gmail_permalink,
            payment_id       = excluded.payment_id
        """,
        (
            reference,
            txn_date.isoformat(),
            description,
            currency,
            amount,
            merchant,
            location,
            card_id,
            cardholder_id,
            authorization,
            category,
            gmail_message_id,
            gmail_permalink,
            payment_id,
        ),
    )


def existing_references(conn: sqlite3.Connection) -> set[str]:
    return {row["reference"] for row in conn.execute("SELECT reference FROM transactions")}


def prune_missing(
    conn: sqlite3.Connection, references: set[str], payment_ids: set[str]
) -> int:
    """Drops local rows that no longer exist in the Sheet."""
    pruned = 0
    existing = {row["reference"] for row in conn.execute("SELECT reference FROM transactions")}
    stale = existing - references
    for reference in stale:
        conn.execute("DELETE FROM transactions WHERE reference = ?", (reference,))
    pruned += len(stale)

    existing_payments = {row["id"] for row in conn.execute("SELECT id FROM payments")}
    stale_payments = existing_payments - payment_ids
    for payment_id in stale_payments:
        conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
    pruned += len(stale_payments)

    return pruned


def list_transactions(
    conn: sqlite3.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
    cardholder_id: int | None = None,
    card_id: int | None = None,
    paid: bool | None = None,
) -> tuple[list[sqlite3.Row], dict[str, float]]:
    clauses, params = [], []
    if start_date:
        clauses.append("t.txn_date >= ?")
        params.append(start_date.isoformat())
    if end_date:
        clauses.append("t.txn_date <= ?")
        params.append(end_date.isoformat())
    if cardholder_id:
        clauses.append("t.cardholder_id = ?")
        params.append(cardholder_id)
    if card_id:
        clauses.append("t.card_id = ?")
        params.append(card_id)
    if paid is not None:
        clauses.append("t.payment_id IS NOT NULL" if paid else "t.payment_id IS NULL")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"{TRANSACTION_SELECT}{where} ORDER BY t.txn_date DESC, t.id DESC", params
    ).fetchall()

    totals: dict[str, float] = {}
    for row in rows:
        totals[row["currency"]] = totals.get(row["currency"], 0.0) + row["amount"]
    return rows, totals


def list_cardholders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cardholders ORDER BY name").fetchall()


def list_cards(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT c.*, ch.name AS cardholder_name
        FROM cards c JOIN cardholders ch ON ch.id = c.cardholder_id
        ORDER BY ch.name, c.card_type, c.last_digits
        """
    ).fetchall()


def references_for_ids(conn: sqlite3.Connection, transaction_ids: list[int]) -> list[str]:
    """Local ids to Sheet references — the Sheet knows nothing about local ids."""
    if not transaction_ids:
        return []
    placeholders = ",".join("?" * len(transaction_ids))
    rows = conn.execute(
        f"SELECT reference FROM transactions WHERE id IN ({placeholders})", transaction_ids
    ).fetchall()
    return [row["reference"] for row in rows]


def list_payments(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.*, COUNT(t.id) AS covered_count, COALESCE(SUM(t.amount), 0) AS covered_sum
        FROM payments p LEFT JOIN transactions t ON t.payment_id = p.id
        GROUP BY p.id
        ORDER BY p.payment_date DESC, p.id DESC
        """
    ).fetchall()


def get_payment(conn: sqlite3.Connection, payment_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def get_payment_transactions(conn: sqlite3.Connection, payment_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        f"{TRANSACTION_SELECT} WHERE t.payment_id = ? ORDER BY t.txn_date DESC", (payment_id,)
    ).fetchall()


def find_transaction_by_reference(conn: sqlite3.Connection, reference: str) -> sqlite3.Row | None:
    return conn.execute(f"{TRANSACTION_SELECT} WHERE t.reference = ?", (reference,)).fetchone()
