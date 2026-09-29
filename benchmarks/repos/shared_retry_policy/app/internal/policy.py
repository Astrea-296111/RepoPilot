def retryable(status: int) -> bool:
    return status >= 500
