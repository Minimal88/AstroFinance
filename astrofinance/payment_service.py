"""Payment writes.

The Sheet is authoritative, so every write goes there first and the local
mirror is refreshed by re-pulling. Writing SQLite and pushing later would be
silently destroyed by the next `pull --rebuild`.
"""

from datetime import date, datetime
from uuid import uuid4

from astrofinance import db, pull_service, repository, sheets_client


def _new_payment_id() -> str:
    # Same shape as AppSheet's UNIQUEID(), so ids look uniform whichever client
    # created them.
    return uuid4().hex[:8]


def create_payment(
    payment_date: date,
    amount: float,
    currency: str | None,
    notes: str | None,
    transaction_ids: list[int],
) -> str:
    """Records a payment covering the given local transaction ids.

    Raises ValueError if any target is already covered by another payment.
    """
    with db.get_connection() as conn:
        references = repository.references_for_ids(conn, transaction_ids)

    if not references:
        raise ValueError("Select at least one transaction.")

    service = sheets_client.get_service()

    # Re-read assignments immediately before writing so a payment marked from
    # the phone in the meantime is respected rather than clobbered.
    assignments = sheets_client.read_payment_assignments(service)

    missing = [reference for reference in references if reference not in assignments]
    if missing:
        raise ValueError(f"Not found in the Sheet (pull first): {', '.join(missing)}")

    already_paid = [
        reference for reference in references if assignments[reference]["payment_id"]
    ]
    if already_paid:
        raise ValueError(
            f"Transactions already covered by another payment: {', '.join(already_paid)}"
        )

    payment_id = _new_payment_id()
    sheets_client.append_payment(
        service,
        [
            payment_id,
            payment_date.isoformat(),
            amount,
            currency or "",
            notes or "",
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        ],
    )
    sheets_client.set_payment_ids(
        service, {assignments[reference]["row"]: payment_id for reference in references}
    )

    pull_service.run_pull()
    return payment_id


def delete_payment(payment_id: str) -> None:
    """Deletes a payment and returns its transactions to pending."""
    with db.get_connection() as conn:
        references = [
            row["reference"] for row in repository.get_payment_transactions(conn, payment_id)
        ]

    service = sheets_client.get_service()
    assignments = sheets_client.read_payment_assignments(service)

    sheets_client.set_payment_ids(
        service,
        {
            assignments[reference]["row"]: ""
            for reference in references
            if reference in assignments
        },
    )
    sheets_client.delete_payment_row(service, payment_id)

    pull_service.run_pull()
