def check_limit(now: int, window_start: int, count: int, limit: int, window_seconds: int):
    if now - window_start > window_seconds:
        return True, now, 1
    if count >= limit:
        return False, window_start, count
    return True, window_start, count + 1
