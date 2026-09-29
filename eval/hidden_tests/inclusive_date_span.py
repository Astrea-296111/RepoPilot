from datetime import date
import pytest
from app.dates import date_span_days


def test_multi_day_range_is_inclusive():
    assert date_span_days(date(2026, 1, 1), date(2026, 1, 3)) == 3


def test_reverse_range_stays_invalid():
    with pytest.raises(ValueError):
        date_span_days(date(2026, 1, 2), date(2026, 1, 1))
