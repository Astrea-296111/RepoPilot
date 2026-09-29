def backoff_seconds(attempt: int, base: int = 1, cap: int = 30) -> int:
    if attempt < 1 or base < 0 or cap < 0:
        raise ValueError("invalid retry parameters")
    return min(cap, base * (2 ** attempt))
