def choose(default: bool, config: dict, env: dict, name: str) -> bool:
    value = default
    if name in env:
        value = env[name].lower() == "true"
    if name in config:
        value = bool(config[name])
    return value
