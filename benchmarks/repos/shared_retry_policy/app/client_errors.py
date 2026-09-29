def is_client_error(status: int) -> bool:
    return 400 <= status < 500
