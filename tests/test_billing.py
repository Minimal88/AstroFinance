from datetime import date

import pytest

from astrofinance.billing import (
    AMEX,
    VISA_MC,
    CardFamily,
    card_family_id,
    next_payment_offset,
    statement,
    statement_for_view,
)

VISA = CardFamily(VISA_MC, "Visa · Mastercard", cutoff_day=21, pay_day=5)
AMEX_CARD = CardFamily(AMEX, "Amex", cutoff_day=27, pay_day=12)


def span(st):
    return st.start, st.end, st.due


def test_open_statement_runs_from_day_after_previous_cutoff():
    assert span(statement(VISA, 0, date(2026, 10, 28))) == (date(2026, 10, 22), date(2026, 11, 21), date(2026, 12, 5))


def test_cutoff_day_belongs_to_the_closing_statement():
    st = statement(AMEX_CARD, 0, date(2026, 10, 27))
    assert span(st) == (date(2026, 9, 28), date(2026, 10, 27), date(2026, 11, 12))
    assert st.is_open


def test_day_after_cutoff_starts_a_new_statement():
    assert statement(AMEX_CARD, 0, date(2026, 10, 28)).start == date(2026, 10, 28)


def test_pay_day_after_cutoff_day_is_due_the_same_month():
    family = CardFamily(VISA_MC, "Test", cutoff_day=5, pay_day=20)
    assert statement(family, 0, date(2026, 10, 3)).due == date(2026, 10, 20)


def test_cutoff_clamped_to_shorter_month():
    family = CardFamily(VISA_MC, "Test", cutoff_day=31, pay_day=15)
    assert span(statement(family, 0, date(2026, 2, 20))) == (date(2026, 2, 1), date(2026, 2, 28), date(2026, 3, 15))


def test_statement_crosses_year_boundary():
    assert span(statement(VISA, 0, date(2026, 12, 28))) == (date(2026, 12, 22), date(2027, 1, 21), date(2027, 2, 5))


@pytest.mark.parametrize(
    "today, family, expected_end, expected_due",
    [
        # Visa closed Oct 21 and is due Nov 5: that is still the next payment.
        (date(2026, 10, 28), VISA, date(2026, 10, 21), date(2026, 11, 5)),
        # Amex closed Sep 27 and was due Oct 12, so the next payment is the Oct 27 statement.
        (date(2026, 10, 28), AMEX_CARD, date(2026, 10, 27), date(2026, 11, 12)),
        # On the due date the payment is still upcoming.
        (date(2026, 11, 5), VISA, date(2026, 10, 21), date(2026, 11, 5)),
        # The day after, the next payment moves to the open statement.
        (date(2026, 11, 6), VISA, date(2026, 11, 21), date(2026, 12, 5)),
    ],
)
def test_next_payment(today, family, expected_end, expected_due):
    st = statement(family, next_payment_offset(family, today), today)
    assert (st.end, st.due) == (expected_end, expected_due)


def test_following_and_previous_views():
    today = date(2026, 10, 28)
    assert statement_for_view(VISA, "following", today).end == date(2026, 11, 21)
    assert statement_for_view(VISA, "previous", today).end == date(2026, 9, 21)


@pytest.mark.parametrize(
    "card_type, expected",
    [("AMEX", AMEX), ("amex ", AMEX), ("VISA", VISA_MC), ("MASTER", VISA_MC), ("UNKNOWN", VISA_MC), (None, VISA_MC)],
)
def test_card_family_id(card_type, expected):
    assert card_family_id(card_type) == expected
