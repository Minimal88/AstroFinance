import calendar
from datetime import date


def _cutoff_for_month(year: int, month: int, cutoff_day: int) -> date:
    return date(year, month, min(cutoff_day, calendar.monthrange(year, month)[1]))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def get_current_billing_period(cutoff_day: int, today: date | None = None) -> tuple[date, date]:
    """Period running from the most recent cutoff day up to the next one."""
    today = today or date.today()
    this_month_cutoff = _cutoff_for_month(today.year, today.month, cutoff_day)

    if today >= this_month_cutoff:
        start = this_month_cutoff
        end = _cutoff_for_month(*_shift_month(today.year, today.month, 1), cutoff_day)
    else:
        start = _cutoff_for_month(*_shift_month(today.year, today.month, -1), cutoff_day)
        end = this_month_cutoff

    return start, end
