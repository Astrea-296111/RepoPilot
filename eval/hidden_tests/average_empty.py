from app.stats import average


def test_non_empty_average_still_works():
    assert average([1, 2, 6]) == 3
