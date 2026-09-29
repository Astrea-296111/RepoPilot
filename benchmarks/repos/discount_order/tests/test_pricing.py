from app.pricing import final_price


def test_percentage_is_applied_before_coupon():
    assert final_price(100, 10, 20) == 70.0
