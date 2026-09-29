from app.collections import dedupe


def test_already_unique_order_is_unchanged():
    assert dedupe(["z", "x", "y"]) == ["z", "x", "y"]
