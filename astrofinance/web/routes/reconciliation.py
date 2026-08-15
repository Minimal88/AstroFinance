from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from astrofinance import db, reconcile
from astrofinance.web.templating import templates

router = APIRouter(prefix="/reconciliation")


@router.get("", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "reconciliation/upload.html",
        {"report": None, "column_map": reconcile.CSV_COLUMN_MAP},
    )


@router.post("", response_class=HTMLResponse)
async def run_reconciliation(request: Request, statement: UploadFile = File(...)) -> HTMLResponse:
    csv_text = (await statement.read()).decode("utf-8-sig", errors="replace")
    with db.get_connection() as conn:
        report = reconcile.reconcile(conn, csv_text)
    return templates.TemplateResponse(
        request,
        "reconciliation/upload.html",
        {"report": report, "column_map": reconcile.CSV_COLUMN_MAP},
    )
