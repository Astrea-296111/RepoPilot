from .internal.path_ops import resolve_config_path


def cache_path(config_file: str, value: str):
    return resolve_config_path(config_file, value)
