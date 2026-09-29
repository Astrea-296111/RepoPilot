import pytest
from app.users import normalize_username


def test_whitespace_only_is_rejected():
    with pytest.raises(ValueError):
        normalize_username("   ")


def test_internal_spaces_are_preserved():
    assert normalize_username(" Mary Jane ") == "mary jane"
