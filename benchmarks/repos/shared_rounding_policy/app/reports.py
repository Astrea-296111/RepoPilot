from .internal.number_ops import money


def report_total(amount: float) -> float:
    return money(amount)
