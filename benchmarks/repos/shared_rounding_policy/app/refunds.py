from .internal.number_ops import money


def refund_total(amount: float) -> float:
    return money(amount)
