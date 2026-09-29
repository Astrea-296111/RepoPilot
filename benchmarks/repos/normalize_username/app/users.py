def normalize_username(value: str) -> str:
    normalized = value.lower()
    if not normalized:
        raise ValueError("username is empty")
    return normalized
