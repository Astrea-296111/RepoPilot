import pytest
from app.env import parse_bool


def test_supported_true_and_false_values():
    for value in ["1", "TRUE", " yes ", "On"]:
        assert parse_bool(value) is True
    for value in ["0", "FALSE", " no ", "Off"]:
        assert parse_bool(value) is False


def test_unknown_value_is_rejected():
    with pytest.raises(ValueError):
        parse_bool("maybe")
