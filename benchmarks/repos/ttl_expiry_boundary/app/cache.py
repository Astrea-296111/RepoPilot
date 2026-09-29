def is_expired(created_at: int, now: int, ttl_seconds: int) -> bool:
    if ttl_seconds < 0:
        raise ValueError("ttl must be non-negative")
    age = now - created_at
    return age > ttl_seconds
