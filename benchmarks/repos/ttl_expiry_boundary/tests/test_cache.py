from app.cache import is_expired


def test_exact_ttl_is_expired():
    assert is_expired(100, 110, 10) is True
