from .internal.policy import retryable


def should_retry_background(status: int) -> bool:
    return retryable(status)
