def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    result.update(override)
    return result
