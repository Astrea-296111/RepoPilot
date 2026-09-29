from pathlib import Path


def resolve_config_path(config_file: str | Path, value: str) -> Path:
    return Path(value).resolve()
