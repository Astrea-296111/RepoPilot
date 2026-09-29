from datetime import date
from app.dates import date_span_days


def test_same_day_counts_as_one():
    assert date_span_days(date(2026, 1, 1), date(2026, 1, 1)) == 1
