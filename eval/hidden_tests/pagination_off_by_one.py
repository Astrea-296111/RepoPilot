import pytest
from app.pagination import paginate


def test_second_and_partial_pages():
    items = [1, 2, 3, 4, 5]
    assert paginate(items, 2, 2) == [3, 4]
    assert paginate(items, 3, 2) == [5]


def test_invalid_page_is_still_rejected():
    with pytest.raises(ValueError):
        paginate([1, 2], 0, 2)
