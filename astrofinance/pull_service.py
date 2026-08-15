"""Mirrors the Google Sheet into the local SQLite cache.

The Sheet is the system of record. SQLite exists so the existing filtering,
billing-period and reconciliation queries keep working against SQL — it holds
nothing that cannot be rebuilt from the Sheet.
"""

from astrofinance import db, repository, sheets_client
from astrofinance.dates import parse_date
from astrofinance.models import PullResult


def _to_float(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def run_pull(rebuild: bool = False, prune: bool = True) -> PullResult:
    result = PullResult()
    service = sheets_client.get_service()
    transactions, payments = sheets_client.read_tabs(service)

    db.init_db()
    with db.get_connection() as conn:
        if rebuild:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM payments")

        for row in payments:
            payment_id = str(row["PaymentID"]).strip()
            payment_date = parse_date(row["PaymentDate"])
            amount = _to_float(row["Amount"])
            if not payment_id or payment_date is None or amount is None:
                result.errors.append(f"payment {payment_id or '(no id)'}: bad date or amount")
                continue
            repository.upsert_payment(
                conn,
                payment_id=payment_id,
                payment_date=payment_date,
                amount=amount,
                currency=str(row["Currency"] or "").strip() or None,
                notes=str(row["Notes"] or "").strip() or None,
            )

        known_payment_ids = {str(row["PaymentID"]).strip() for row in payments}
        # Captured before the loop: an upsert cannot report which branch it took.
        seen_before = repository.existing_references(conn)

        for row in transactions:
            reference = str(row["Reference"]).strip()
            txn_date = parse_date(row["TxnDate"])
            amount = _to_float(row["Amount"])
            if txn_date is None or amount is None:
                result.errors.append(f"transaction {reference}: bad date or amount")
                continue

            payment_id = str(row["PaymentID"] or "").strip() or None
            if payment_id and payment_id not in known_payment_ids:
                result.errors.append(
                    f"transaction {reference}: references unknown payment {payment_id}"
                )
                payment_id = None

            cardholder_id = repository.get_or_create_cardholder(
                conn, str(row["CardholderName"] or "UNKNOWN").strip() or "UNKNOWN"
            )
            card_id = repository.get_or_create_card(
                conn,
                cardholder_id,
                str(row["CardType"] or "UNKNOWN").strip() or "UNKNOWN",
                str(row["LastDigits"] or "").strip(),
            )

            repository.upsert_transaction(
                conn,
                reference=reference,
                txn_date=txn_date,
                description=str(row["Description"] or ""),
                currency=str(row["Currency"] or "").strip(),
                amount=amount,
                merchant=str(row["Merchant"] or ""),
                location=str(row["Location"] or ""),
                card_id=card_id,
                cardholder_id=cardholder_id,
                authorization=str(row["Authorization"] or ""),
                category=str(row["Category"] or "").strip() or None,
                gmail_message_id=str(row["GmailMessageId"] or "").strip() or None,
                gmail_permalink=str(row["GmailPermalink"] or "").strip() or None,
                payment_id=payment_id,
            )
            if reference in seen_before:
                result.updated += 1
            else:
                result.new += 1

        if prune:
            result.pruned = repository.prune_missing(
                conn,
                references={str(row["Reference"]).strip() for row in transactions},
                payment_ids=known_payment_ids,
            )

        conn.commit()

    return result
