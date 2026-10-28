"""Card statements.

Each card family closes its statement on its own cutoff day and is due on its
own pay day. A statement covers the day after the previous cutoff through the
cutoff day itself. It is due on the pay day of the following month when the pay
day comes before the cutoff day (cutoff 21, pay 5), otherwise in the same month.

Keep this in step with the statement maths in app/astrofinance.html.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

AMEX = "amex"
VISA_MC = "visamc"

VIEWS = {
    "next": "Next payment",
    "following": "Following statement",
    "previous": "Previous statement",
}


@dataclass(frozen=True)
class CardFamily:
    id: str
    name: str
    cutoff_day: int
    pay_day: int


@dataclass(frozen=True)
class Statement:
    family: CardFamily
    start: date
    end: date
    due: date
    is_open: bool


def current_date() -> date:
    """Today's date; one place for tests to freeze it."""
    return date.today()


def card_family_id(card_type: str | None) -> str:
    """Amex cards bill on their own cycle; every other card type bills as Visa/Mastercard."""
    return AMEX if (card_type or "").strip().upper() == AMEX.upper() else VISA_MC


def _day_in_month(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def statement(family: CardFamily, offset: int = 0, today: date | None = None) -> Statement:
    """The statement `offset` cycles away from the one that contains today (0)."""
    today = today or current_date()
    year, month = today.year, today.month
    if today > _day_in_month(year, month, family.cutoff_day):
        year, month = _shift_month(year, month, 1)
    year, month = _shift_month(year, month, offset)

    end = _day_in_month(year, month, family.cutoff_day)
    start = _day_in_month(*_shift_month(year, month, -1), family.cutoff_day) + timedelta(days=1)
    due_month = _shift_month(year, month, 1 if family.pay_day <= family.cutoff_day else 0)
    due = _day_in_month(*due_month, family.pay_day)
    return Statement(family, start, end, due, is_open=end >= today)


def next_payment_offset(family: CardFamily, today: date | None = None) -> int:
    """Offset of the statement whose due date is the next one coming up."""
    today = today or current_date()
    for offset in range(-2, 2):
        if statement(family, offset, today).due >= today:
            return offset
    return 0


def statement_for_view(family: CardFamily, view: str, today: date | None = None) -> Statement:
    """`view` is one of VIEWS: the next payment, or the statement after or before it."""
    base = next_payment_offset(family, today)
    shift = {"next": 0, "following": 1, "previous": -1}[view]
    return statement(family, base + shift, today)
