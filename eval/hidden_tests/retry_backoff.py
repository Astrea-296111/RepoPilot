from app.retry import backoff_seconds


def test_exponential_growth_and_cap():
    assert backoff_seconds(2, base=2, cap=30) == 4
    assert backoff_seconds(3, base=2, cap=30) == 8
    assert backoff_seconds(10, base=2, cap=30) == 30
