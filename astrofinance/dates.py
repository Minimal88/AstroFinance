from datetime import date, datetime

# The Apps Script always writes ISO. AppSheet writes PaymentDate in the app's
# locale format, and bank CSV exports use whatever they use, so parsing has to
# be tolerant.
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"]


def parse_date(raw: str | date | None) -> date | None:
    """Parses a date from any of DATE_FORMATS. Returns None if unrecognized."""
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
