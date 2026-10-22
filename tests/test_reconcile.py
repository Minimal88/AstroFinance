from datetime import date

import pytest
from fastapi.testclient import TestClient

from astrofinance import config, db, reconcile, repository
from astrofinance.web.routes.reconciliation import decode_column_cookie


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db(path)
    with db.get_connection(path) as connection:
        holder = repository.get_or_create_cardholder(connection, "Ana")
        card = repository.get_or_create_card(connection, holder, "VISA", "1234")
        for reference, day, amount in [
            ("REF1", date(2026, 9, 1), 100.00),
            ("REF2", date(2026, 9, 5), 25.50),
            ("REF3", date(2026, 9, 5), 25.50),
            ("REF4", date(2026, 9, 20), 9.99),
            ("OLD", date(2026, 6, 1), 50.00),
        ]:
            repository.upsert_transaction(
                connection, reference, day, "desc", "USD", amount, "Shop", "CR", card, holder, "AUTH"
            )
        connection.commit()
        yield connection


def _refs(entries):
    return sorted(entry["transaction"]["reference"] for entry in entries)


SPANISH_HEADERS = ["Fecha de transacción", "Descripción", "Número de referencia", "Monto"]


def test_guess_column_map_spanish_headers():
    assert reconcile.guess_column_map(SPANISH_HEADERS) == {
        "reference": "Número de referencia",
        "amount": "Monto",
        "date": "Fecha de transacción",
    }


def test_guess_column_map_english_headers():
    assert reconcile.guess_column_map(["Date", "Merchant", "Amount", "Reference"]) == {
        "reference": "Reference",
        "amount": "Amount",
        "date": "Date",
    }


def test_guess_column_map_leaves_unknown_fields_empty():
    assert reconcile.guess_column_map(["Foo", "Bar"]) == {"reference": None, "amount": None, "date": None}


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,234.56", 1234.56),
        ("1.234,56", 1234.56),
        ("₡12 500,00", 12500.00),
        ("-45.10", 45.10),
        ("(45.10)", 45.10),
        ("$1,234", 1234.0),
        ("25,5", 25.5),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_amount(raw, expected):
    assert reconcile.parse_amount(raw) == expected


def test_matches_by_reference_then_amount_and_date(conn):
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,100.00\n2026-09-21,,9.99\n"
    report = reconcile.reconcile(conn, csv_text)
    assert _refs(report.matched) == ["REF1", "REF4"]
    assert report.missing_in_db == []


def test_same_amount_rows_match_different_transactions(conn):
    # Two identical charges on the same day must not both claim REF2.
    csv_text = "Fecha,Referencia,Monto\n2026-09-05,,25.50\n2026-09-05,,25.50\n"
    report = reconcile.reconcile(conn, csv_text)
    assert _refs(report.matched) == ["REF2", "REF3"]


def test_third_identical_row_is_missing_locally(conn):
    csv_text = "Fecha,Monto\n2026-09-05,25.50\n2026-09-05,25.50\n2026-09-05,25.50\n"
    report = reconcile.reconcile(conn, csv_text)
    assert len(report.matched) == 2
    assert len(report.missing_in_db) == 1


def test_duplicate_reference_is_flagged(conn):
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,100.00\n2026-09-01,REF1,100.00\n"
    report = reconcile.reconcile(conn, csv_text)
    assert _refs(report.matched) == ["REF1"]
    assert _refs(report.mismatched) == ["REF1"]
    assert "more than once" in report.mismatched[0]["reason"]


def test_amount_difference_is_mismatched(conn):
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,101.00\n"
    report = reconcile.reconcile(conn, csv_text)
    assert _refs(report.mismatched) == ["REF1"]


def test_negative_statement_amounts_still_match(conn):
    csv_text = "Fecha,Monto\n01/09/2026,-100.00\n"
    report = reconcile.reconcile(conn, csv_text)
    assert _refs(report.matched) == ["REF1"]


def test_date_outside_tolerance_does_not_match(conn):
    csv_text = "Fecha,Monto\n2026-09-10,100.00\n"
    report = reconcile.reconcile(conn, csv_text)
    assert report.matched == []
    assert len(report.missing_in_db) == 1


def test_missing_in_statement_limited_to_statement_period(conn):
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,100.00\n2026-09-05,REF2,25.50\n"
    report = reconcile.reconcile(conn, csv_text)
    assert report.period == (date(2026, 9, 1), date(2026, 9, 5))
    # REF3 is inside the period; REF4 (later) and OLD (earlier) are not.
    assert [txn["reference"] for txn in report.missing_in_statement] == ["REF3"]


def test_explicit_column_map_is_used(conn):
    csv_text = "When,Ticket,Total\n2026-09-01,REF1,100.00\n"
    report = reconcile.reconcile(conn, csv_text, {"reference": "Ticket", "amount": "Total", "date": "When"})
    assert _refs(report.matched) == ["REF1"]


def test_blank_lines_are_ignored(conn):
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,100.00\n,,\n"
    report = reconcile.reconcile(conn, csv_text)
    assert report.missing_in_db == []


@pytest.fixture
def client(conn):
    from astrofinance.web.app import app

    with TestClient(app) as test_client:
        yield test_client


def test_upload_guesses_columns_and_reports(client):
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,100.00\n"
    response = client.post("/reconciliation", files={"statement": ("s.csv", csv_text, "text/csv")})
    assert response.status_code == 200
    assert '<option value="Referencia" selected>' in response.text
    assert "Statement covers 2026-09-01 to 2026-09-01" in response.text


def test_rerun_with_columns_remembers_choice(client):
    csv_text = "Fecha de transacción,Ticket,Total\n2026-09-01,REF1,100.00\n"
    response = client.post(
        "/reconciliation",
        data={"csv_text": csv_text, "reference_col": "Ticket", "amount_col": "Total", "date_col": "Fecha de transacción"},
    )
    assert response.status_code == 200
    assert '<option value="Ticket" selected>' in response.text
    saved = decode_column_cookie(client.cookies.get("reconcile_columns"))
    assert saved == {"reference": "Ticket", "amount": "Total", "date": "Fecha de transacción"}

    # The next upload with the same headers reuses the remembered columns.
    response = client.post("/reconciliation", files={"statement": ("s.csv", csv_text, "text/csv")})
    assert '<option value="Total" selected>' in response.text


def test_post_without_csv_is_rejected(client):
    response = client.post("/reconciliation", data={})
    assert response.status_code == 400


def test_upload_form_renders(client):
    response = client.get("/reconciliation")
    assert response.status_code == 200
    assert 'name="statement"' in response.text


def test_bad_cookie_falls_back_to_guess(client):
    client.cookies.set("reconcile_columns", "not-base64!")
    csv_text = "Fecha,Referencia,Monto\n2026-09-01,REF1,100.00\n"
    response = client.post("/reconciliation", files={"statement": ("s.csv", csv_text, "text/csv")})
    assert '<option value="Monto" selected>' in response.text
