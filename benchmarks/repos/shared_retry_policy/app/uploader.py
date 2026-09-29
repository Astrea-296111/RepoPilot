from .internal.policy import retryable


def should_retry_upload(status: int) -> bool:
    return retryable(status)
