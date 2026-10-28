import os
from pathlib import Path

from dotenv import load_dotenv

from astrofinance.billing import AMEX, VISA_MC, CardFamily

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

SPREADSHEET_ID_PLACEHOLDER = "REPLACE_WITH_YOUR_SPREADSHEET_ID"

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", SPREADSHEET_ID_PLACEHOLDER)
# Statement cutoff and payment due day for each card family.
CARD_FAMILIES = {
    VISA_MC: CardFamily(
        VISA_MC,
        "Visa · Mastercard",
        cutoff_day=int(os.getenv("VISA_MC_CUTOFF_DAY", "21")),
        pay_day=int(os.getenv("VISA_MC_PAY_DAY", "5")),
    ),
    AMEX: CardFamily(
        AMEX,
        "Amex",
        cutoff_day=int(os.getenv("AMEX_CUTOFF_DAY", "27")),
        pay_day=int(os.getenv("AMEX_PAY_DAY", "12")),
    ),
}

TRANSACTIONS_TAB = os.getenv("TRANSACTIONS_TAB", "Transactions")
PAYMENTS_TAB = os.getenv("PAYMENTS_TAB", "Payments")

# Read/write: the app appends payments and sets PaymentID on transactions.
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _resolve(env_name: str, default: str) -> Path:
    value = Path(os.getenv(env_name, default))
    return value if value.is_absolute() else PROJECT_ROOT / value


GOOGLE_SERVICE_ACCOUNT_PATH = _resolve(
    "GOOGLE_SERVICE_ACCOUNT_PATH", "credentials/service_account.json"
)
DB_PATH = _resolve("ASTROFINANCE_DB_PATH", "data/astrofinance.db")
