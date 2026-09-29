import pytest
from app.cache import is_expired


def test_before_and_after_boundary():
    assert is_expired(100, 109, 10) is False
    assert is_expired(100, 111, 10) is True
    assert is_expired(100, 100, 0) is True


def test_negative_ttl_stays_invalid():
    with pytest.raises(ValueError):
        is_expired(0, 0, -1)
