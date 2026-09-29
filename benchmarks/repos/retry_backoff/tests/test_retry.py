from app.retry import backoff_seconds


def test_first_attempt_uses_base_delay():
    assert backoff_seconds(1, base=2, cap=30) == 2
