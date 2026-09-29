from .internal.policy import retryable


def should_retry_request(status: int) -> bool:
    return retryable(status)
