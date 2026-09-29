def resolve_timeout(default: int, config: dict, env: dict) -> int:
    timeout = default
    if env.get("APP_TIMEOUT"):
        timeout = int(env["APP_TIMEOUT"])
    if "timeout" in config:
        timeout = int(config["timeout"])
    return timeout
