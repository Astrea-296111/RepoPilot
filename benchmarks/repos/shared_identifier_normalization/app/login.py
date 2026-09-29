from .internal.value_ops import normalize


def same_login(stored: str, supplied: str) -> bool:
    return normalize(stored) == normalize(supplied)
