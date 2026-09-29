from app.stats import average


def test_empty_average_is_none():
    assert average([]) is None
