from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from astrofinance import billing, config, db, repository
from astrofinance.dates import parse_date
from astrofinance.web.templating import templates

router = APIRouter()


@router.get("/transactions", response_class=HTMLResponse)
def list_transactions(
    request: Request,
    view: str = "next",
    family: str = "",
    start_date: str = "",
    end_date: str = "",
    cardholder_id: str = "",
    card_id: str = "",
    status: str = "all",
    pulled: int | None = None,
) -> HTMLResponse:
    # The filter form submits empty strings for fields left blank.
    start_date, end_date = parse_date(start_date), parse_date(end_date)
    cardholder_id = int(cardholder_id) if cardholder_id.strip().isdigit() else None
    card_id = int(card_id) if card_id.strip().isdigit() else None

    # Both dates given means a custom range; otherwise each card family is
    # filtered by its own statement for the chosen view.
    custom = start_date is not None and end_date is not None
    if view not in billing.VIEWS:
        view = "next"
    if family not in config.CARD_FAMILIES:
        family = ""
    families = {fid: fam for fid, fam in config.CARD_FAMILIES.items() if not family or fid == family}
    statements = {fid: billing.statement_for_view(fam, view) for fid, fam in config.CARD_FAMILIES.items()}

    paid = {"paid": True, "pending": False}.get(status)
    if custom:
        family_ranges = {fid: (start_date, end_date) for fid in families}
    else:
        family_ranges = {fid: (statements[fid].start, statements[fid].end) for fid in families}

    with db.get_connection() as conn:
        rows, totals = repository.list_transactions(
            conn, None, None, cardholder_id, card_id, paid, family_ranges=family_ranges
        )
        tiles = []
        for fid, st in statements.items():
            span = {fid: (st.start, st.end)}
            items, item_totals = repository.list_transactions(
                conn, None, None, cardholder_id, card_id, family_ranges=span
            )
            pending, pending_totals = repository.list_transactions(
                conn, None, None, cardholder_id, card_id, False, family_ranges=span
            )
            tiles.append(
                {
                    "statement": st,
                    "days_to_due": (st.due - billing.current_date()).days,
                    "count": len(items),
                    "totals": item_totals,
                    "pending_count": len(pending),
                    "pending_totals": pending_totals,
                    "selected": family == fid,
                }
            )
        cardholders = repository.list_cardholders(conn)
        cards = repository.list_cards(conn)

    context = {
        "transactions": rows,
        "totals": totals,
        "tiles": tiles,
        "views": billing.VIEWS,
        "view": view,
        "custom": custom,
        "family": family,
        "families": config.CARD_FAMILIES,
        "cardholders": cardholders,
        "cards": cards,
        "start_date": start_date if custom else None,
        "end_date": end_date if custom else None,
        "cardholder_id": cardholder_id,
        "card_id": card_id,
        "status": status,
        "pulled": pulled,
    }

    return templates.TemplateResponse(request, "transactions/list.html", context)
