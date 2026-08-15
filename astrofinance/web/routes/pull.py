from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from astrofinance import pull_service

router = APIRouter()


@router.post("/pull")
def run_pull() -> RedirectResponse:
    try:
        result = pull_service.run_pull()
    except Exception as exc:
        return RedirectResponse(f"/transactions?pulled=0&error={quote(str(exc))}", status_code=303)

    return RedirectResponse(
        f"/transactions?pulled=1&new={result.new}&updated={result.updated}"
        f"&pruned={result.pruned}&errors={len(result.errors)}",
        status_code=303,
    )
