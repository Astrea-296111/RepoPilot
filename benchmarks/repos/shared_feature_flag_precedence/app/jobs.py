from .internal.select import choose


def job_feature_enabled(default: bool, config: dict, env: dict, name: str) -> bool:
    return choose(default, config, env, name)
