from datetime import date

import pytest
from fastapi.testclient import TestClient

from astrofinance import billing, config, db, repository


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db(path)
    with db.get_connection(path) as conn:
        holder = repository.get_or_create_cardholder(conn, "Ana")
        visa = repository.get_or_create_card(conn, holder, "VISA", "1111")
        amex = repository.get_or_create_card(conn, holder, "AMEX", "2222")
        rows = [
            # Visa statement Sep 22 - Oct 21 (due Nov 5) vs Amex Sep 28 - Oct 27 (due Nov 12).
            ("V-IN", date(2026, 10, 21), visa),
            ("V-OUT", date(2026, 10, 22), visa),
            ("A-IN", date(2026, 10, 25), amex),
            ("A-OUT", date(2026, 9, 27), amex),
        ]
        for reference, day, card in rows:
            repository.upsert_transaction(
                conn, reference, day, "COMPRA", "CRC", 1000.0, reference, "CR", card, holder, "1"
            )
        conn.commit()

    # Freeze "today" to Oct 28, 2026 for the statement maths.
    monkeypatch.setattr(billing, "current_date", lambda: date(2026, 10, 28))

    from astrofinance.web.app import app

    with TestClient(app) as test_client:
        yield test_client


def refs(html):
    return sorted(ref for ref in ["V-IN", "V-OUT", "A-IN", "A-OUT"] if f'<td class="ref">{ref}</td>' in html)


def test_next_payment_filters_each_card_by_its_own_statement(client):
    response = client.get("/transactions")
    assert response.status_code == 200
    assert refs(response.text) == ["A-IN", "V-IN"]
    assert "Due Nov 05" in response.text and "Due Nov 12" in response.text


def test_one_card_family(client):
    assert refs(client.get("/transactions?family=amex").text) == ["A-IN"]


def test_following_statement(client):
    assert refs(client.get("/transactions?view=following").text) == ["V-OUT"]


def test_custom_range_overrides_statements(client):
    html = client.get("/transactions?start_date=2026-09-01&end_date=2026-12-31").text
    assert refs(html) == ["A-IN", "A-OUT", "V-IN", "V-OUT"]


def test_blank_form_fields_are_accepted(client):
    response = client.get("/transactions?view=next&family=&start_date=&end_date=&cardholder_id=&card_id=&status=all")
    assert response.status_code == 200
    assert refs(response.text) == ["A-IN", "V-IN"]
