from datetime import date

from astrofinance.billing import get_current_billing_period


def test_period_after_cutoff_runs_to_next_month():
    assert get_current_billing_period(15, date(2026, 8, 20)) == (date(2026, 8, 15), date(2026, 9, 15))


def test_period_before_cutoff_starts_previous_month():
    assert get_current_billing_period(15, date(2026, 8, 3)) == (date(2026, 7, 15), date(2026, 8, 15))


def test_cutoff_day_on_boundary_starts_new_period():
    assert get_current_billing_period(15, date(2026, 8, 15)) == (date(2026, 8, 15), date(2026, 9, 15))


def test_cutoff_day_clamped_to_shorter_month():
    assert get_current_billing_period(31, date(2026, 2, 20)) == (date(2026, 1, 31), date(2026, 2, 28))


def test_clamped_cutoff_day_starts_new_period():
    assert get_current_billing_period(31, date(2026, 2, 28)) == (date(2026, 2, 28), date(2026, 3, 31))


def test_period_crosses_year_boundary():
    assert get_current_billing_period(15, date(2026, 12, 20)) == (date(2026, 12, 15), date(2027, 1, 15))
