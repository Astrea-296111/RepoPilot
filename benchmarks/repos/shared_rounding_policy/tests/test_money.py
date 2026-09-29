from app.orders import order_total
from app.refunds import refund_total


def test_half_up_rounding_for_order_and_refund():
    assert order_total(10.005) == 10.01
    assert refund_total(2.675) == 2.68
