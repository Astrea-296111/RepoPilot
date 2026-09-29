from .internal.number_ops import money


def order_total(amount: float) -> float:
    return money(amount)
