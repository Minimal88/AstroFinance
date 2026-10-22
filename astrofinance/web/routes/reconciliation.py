import base64
import binascii
import json

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from astrofinance import db, reconcile
from astrofinance.web.templating import templates

router = APIRouter(prefix="/reconciliation")

# Remembers the last column choice, so the next month's export is mapped
# without touching the dropdowns.
COLUMN_COOKIE = "reconcile_columns"


# Base64 so header names with spaces, commas, quotes or accents survive as a
# cookie value without being quoted.
def encode_column_cookie(column_map: dict[str, str | None]) -> str:
    return base64.urlsafe_b64encode(json.dumps(column_map).encode("utf-8")).decode("ascii")


def decode_column_cookie(value: str) -> dict:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(value.encode("ascii")))
    except (ValueError, binascii.Error):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _saved_map(request: Request, headers: list[str]) -> dict[str, str | None] | None:
    """The remembered mapping, if every column it names exists in this CSV."""
    saved = decode_column_cookie(request.cookies.get(COLUMN_COOKIE, ""))
    mapping = {
        field: saved.get(field) if isinstance(saved.get(field), str) and saved.get(field) else None
        for field in reconcile.FIELDS
    }
    if any(column and column not in headers for column in mapping.values()):
        return None
    return mapping if any(mapping.values()) else None


@router.get("", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "reconciliation/upload.html", {"report": None})


@router.post("", response_class=HTMLResponse)
async def run_reconciliation(
    request: Request,
    statement: UploadFile | None = File(None),
    csv_text: str = Form(""),
    reference_col: str | None = Form(None),
    amount_col: str | None = Form(None),
    date_col: str | None = Form(None),
) -> HTMLResponse:
    # A fresh upload wins; otherwise this is a re-run of the CSV already on the page.
    if statement is not None and statement.filename:
        csv_text = (await statement.read()).decode("utf-8-sig", errors="replace")
        chosen = None
    else:
        chosen = {"reference": reference_col, "amount": amount_col, "date": date_col}

    if not csv_text.strip():
        return templates.TemplateResponse(
            request,
            "reconciliation/upload.html",
            {"report": None, "error": "Choose a CSV file to reconcile."},
            status_code=400,
        )

    headers = reconcile.read_headers(csv_text)
    if chosen is not None:
        column_map = {field: (column or None) for field, column in chosen.items()}
    else:
        column_map = _saved_map(request, headers) or reconcile.guess_column_map(headers)

    with db.get_connection() as conn:
        report = reconcile.reconcile(conn, csv_text, column_map)

    response = templates.TemplateResponse(
        request,
        "reconciliation/upload.html",
        {"report": report, "headers": headers, "csv_text": csv_text, "fields": reconcile.FIELDS},
    )
    if chosen is not None:
        response.set_cookie(COLUMN_COOKIE, encode_column_cookie(column_map), max_age=365 * 24 * 3600, samesite="lax")
    return response
