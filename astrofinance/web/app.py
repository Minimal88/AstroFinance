from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from astrofinance import db
from astrofinance.web.routes import payments, pull, reconciliation, transactions

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="AstroFinance", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(transactions.router)
app.include_router(payments.router)
app.include_router(pull.router)
app.include_router(reconciliation.router)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/transactions")
