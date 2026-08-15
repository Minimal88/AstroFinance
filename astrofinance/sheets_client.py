"""Google Sheets access via a service account.

Service-account keys do not expire, which is why this is not the user OAuth
flow: nothing here needs re-consenting every seven days.

The service account must be granted access to the spreadsheet explicitly
(share the Sheet with its `...iam.gserviceaccount.com` address). Without that
share every call returns 404 — it is the most common first-run failure.
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build

from astrofinance import config

# Column contract, mirroring HEADERS in apps_script/Config.gs.
TRANSACTION_HEADERS = [
    "Reference",
    "TxnDate",
    "Merchant",
    "Description",
    "Location",
    "Currency",
    "Amount",
    "CardType",
    "LastDigits",
    "CardholderName",
    "Authorization",
    "Category",
    "PaymentID",
    "GmailMessageId",
    "GmailPermalink",
    "CreatedAt",
]
PAYMENT_HEADERS = ["PaymentID", "PaymentDate", "Amount", "Currency", "Notes", "CreatedAt"]


class SheetError(Exception):
    pass


def _column_letter(index: int) -> str:
    """0-based column index to A1 letter."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def get_credentials():
    if not config.GOOGLE_SERVICE_ACCOUNT_PATH.exists():
        raise SheetError(
            f"Missing service account key at {config.GOOGLE_SERVICE_ACCOUNT_PATH}. "
            "Create one in Google Cloud Console and share the Sheet with its email."
        )
    return service_account.Credentials.from_service_account_file(
        str(config.GOOGLE_SERVICE_ACCOUNT_PATH), scopes=config.SHEETS_SCOPES
    )


def get_service():
    if config.SPREADSHEET_ID == config.SPREADSHEET_ID_PLACEHOLDER:
        raise SheetError(
            "SPREADSHEET_ID is still the placeholder. Set it in .env to your "
            "AstroFinance spreadsheet ID."
        )
    return build("sheets", "v4", credentials=get_credentials(), cache_discovery=False)


def _rows_to_dicts(values: list[list], expected: list[str], tab: str) -> list[dict]:
    """Maps a value grid onto dicts keyed by header name.

    Reads by header name rather than position, so a column dragged around in
    the Sheet produces a clear error instead of silently shifting every field.
    """
    if not values:
        return []

    header = [str(cell).strip() for cell in values[0]]
    missing = [name for name in expected if name not in header]
    if missing:
        raise SheetError(f"{tab} tab is missing column(s): {', '.join(missing)}")

    index = {name: header.index(name) for name in expected}
    rows = []
    for raw in values[1:]:
        row = {
            name: (raw[position] if position < len(raw) else "")
            for name, position in index.items()
        }
        if str(row[expected[0]]).strip():
            rows.append(row)
    return rows


def read_tabs(service) -> tuple[list[dict], list[dict]]:
    """Reads both tabs in a single batchGet.

    UNFORMATTED_VALUE returns Amount as a real float. The identifier columns
    are Plain-text formatted in the Sheet, so they still come back as strings.
    """
    response = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=config.SPREADSHEET_ID,
            ranges=[
                f"{config.TRANSACTIONS_TAB}!A:{_column_letter(len(TRANSACTION_HEADERS) - 1)}",
                f"{config.PAYMENTS_TAB}!A:{_column_letter(len(PAYMENT_HEADERS) - 1)}",
            ],
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )

    ranges = response.get("valueRanges", [])
    transactions = _rows_to_dicts(
        ranges[0].get("values", []) if len(ranges) > 0 else [],
        TRANSACTION_HEADERS,
        config.TRANSACTIONS_TAB,
    )
    payments = _rows_to_dicts(
        ranges[1].get("values", []) if len(ranges) > 1 else [],
        PAYMENT_HEADERS,
        config.PAYMENTS_TAB,
    )
    return transactions, payments


def append_payment(service, values: list) -> None:
    """Appends one row to the Payments tab.

    Uses values.append so the server picks the target row — no local row-index
    arithmetic to race against AppSheet.
    """
    service.spreadsheets().values().append(
        spreadsheetId=config.SPREADSHEET_ID,
        range=f"{config.PAYMENTS_TAB}!A:{_column_letter(len(PAYMENT_HEADERS) - 1)}",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [values]},
    ).execute()


def read_payment_assignments(service) -> dict[str, dict]:
    """Maps each Reference to its current sheet row number and PaymentID.

    Read fresh immediately before writing, so an assignment made from the phone
    in the meantime is seen rather than clobbered.
    """
    payment_column = _column_letter(TRANSACTION_HEADERS.index("PaymentID"))
    response = (
        service.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=config.SPREADSHEET_ID,
            ranges=[
                f"{config.TRANSACTIONS_TAB}!A:A",
                f"{config.TRANSACTIONS_TAB}!{payment_column}:{payment_column}",
            ],
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )

    ranges = response.get("valueRanges", [])
    references = ranges[0].get("values", []) if len(ranges) > 0 else []
    assignments = ranges[1].get("values", []) if len(ranges) > 1 else []

    result = {}
    for offset, reference_row in enumerate(references[1:], start=2):
        reference = str(reference_row[0]).strip() if reference_row else ""
        if not reference:
            continue
        assigned = ""
        if offset - 1 < len(assignments) and assignments[offset - 1]:
            assigned = str(assignments[offset - 1][0]).strip()
        result[reference] = {"row": offset, "payment_id": assigned}
    return result


def _sheet_id(service, title: str) -> int:
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=config.SPREADSHEET_ID, fields="sheets.properties(sheetId,title)")
        .execute()
    )
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == title:
            return properties["sheetId"]
    raise SheetError(f'Spreadsheet has no tab named "{title}".')


def delete_payment_row(service, payment_id: str) -> None:
    """Removes a payment's row from the Payments tab."""
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=config.SPREADSHEET_ID,
            range=f"{config.PAYMENTS_TAB}!A:A",
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )

    rows = response.get("values", [])
    for offset, row in enumerate(rows[1:], start=2):
        if row and str(row[0]).strip() == payment_id:
            service.spreadsheets().batchUpdate(
                spreadsheetId=config.SPREADSHEET_ID,
                body={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": _sheet_id(service, config.PAYMENTS_TAB),
                                    "dimension": "ROWS",
                                    "startIndex": offset - 1,
                                    "endIndex": offset,
                                }
                            }
                        }
                    ]
                },
            ).execute()
            return


def set_payment_ids(service, updates: dict[int, str]) -> None:
    """Writes PaymentID for the given sheet row numbers in one batchUpdate."""
    if not updates:
        return
    column = _column_letter(TRANSACTION_HEADERS.index("PaymentID"))
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=config.SPREADSHEET_ID,
        body={
            "valueInputOption": "RAW",
            "data": [
                {
                    "range": f"{config.TRANSACTIONS_TAB}!{column}{row}",
                    "values": [[value]],
                }
                for row, value in sorted(updates.items())
            ],
        },
    ).execute()
