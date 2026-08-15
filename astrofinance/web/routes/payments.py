from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from astrofinance import db, payment_service, repository
from astrofinance.web.templating import templates

router = APIRouter(prefix="/payments")


@router.get("", response_class=HTMLResponse)
def list_payments(request: Request) -> HTMLResponse:
    with db.get_connection() as conn:
        payments = repository.list_payments(conn)
    return templates.TemplateResponse(request, "payments/list.html", {"payments": payments})


@router.get("/new", response_class=HTMLResponse)
def new_payment(request: Request, error: str | None = None) -> HTMLResponse:
    with db.get_connection() as conn:
        pending, totals = repository.list_transactions(conn, paid=False)
    return templates.TemplateResponse(
        request,
        "payments/new.html",
        {
            "pending": pending,
            "totals": totals,
            "today": date.today(),
            "error": error,
        },
    )


@router.post("")
def create_payment(
    payment_date: date = Form(...),
    amount: float = Form(...),
    currency: str = Form(""),
    notes: str = Form(""),
    transaction_ids: list[int] = Form(default=[]),
) -> RedirectResponse:
    try:
        payment_id = payment_service.create_payment(
            payment_date, amount, currency or None, notes or None, transaction_ids
        )
    except Exception as exc:
        return RedirectResponse(f"/payments/new?error={exc}", status_code=303)

    return RedirectResponse(f"/payments/{payment_id}", status_code=303)


@router.get("/{payment_id}", response_class=HTMLResponse)
def payment_detail(request: Request, payment_id: str) -> HTMLResponse:
    with db.get_connection() as conn:
        payment = repository.get_payment(conn, payment_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        transactions = repository.get_payment_transactions(conn, payment_id)

    covered_sum = sum(row["amount"] for row in transactions)
    return templates.TemplateResponse(
        request,
        "payments/detail.html",
        {
            "payment": payment,
            "transactions": transactions,
            "covered_sum": covered_sum,
            "delta": payment["amount"] - covered_sum,
        },
    )


@router.post("/{payment_id}/unlink")
def unlink_payment(payment_id: str) -> RedirectResponse:
    try:
        payment_service.delete_payment(payment_id)
    except Exception as exc:
        return RedirectResponse(f"/payments?error={exc}", status_code=303)
    return RedirectResponse("/payments", status_code=303)
