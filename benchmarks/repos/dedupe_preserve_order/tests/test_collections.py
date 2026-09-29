from app.collections import dedupe


def test_first_occurrence_order_is_preserved():
    assert dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]
