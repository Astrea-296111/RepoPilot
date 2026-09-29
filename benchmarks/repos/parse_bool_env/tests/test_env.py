from app.env import parse_bool


def test_false_string_is_false():
    assert parse_bool("false") is False
