from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from astrofinance import billing, config, db, repository
from astrofinance.web.templating import templates

router = APIRouter()


@router.get("/transactions", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    cardholder_id: int | None = None,
    card_id: int | None = None,
    status: str = "all",
    pulled: int | None = None,
) -> HTMLResponse:
    if start_date is None or end_date is None:
        period_start, period_end = billing.get_current_billing_period(config.BILLING_CUTOFF_DAY)
        start_date = start_date or period_start
        end_date = end_date or period_end

    paid = {"paid": True, "pending": False}.get(status)

    with db.get_connection() as conn:
        rows, totals = repository.list_transactions(
            conn, start_date, end_date, cardholder_id, card_id, paid
        )
        cardholders = repository.list_cardholders(conn)
        cards = repository.list_cards(conn)

    context = {
        "transactions": rows,
        "totals": totals,
        "cardholders": cardholders,
        "cards": cards,
        "start_date": start_date,
        "end_date": end_date,
        "cardholder_id": cardholder_id,
        "card_id": card_id,
        "status": status,
        "pulled": pulled,
    }

    return templates.TemplateResponse(request, "transactions/list.html", context)
