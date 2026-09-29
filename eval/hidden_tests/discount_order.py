from app.pricing import final_price


def test_price_never_goes_negative():
    assert final_price(10, 50, 20) == 0.0


def test_zero_discount_behaves_normally():
    assert final_price(50, 0, 5) == 45.0
