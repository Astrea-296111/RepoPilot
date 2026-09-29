def filter_files(names: list[str], extension: str) -> list[str]:
    return [name for name in names if name.endswith(extension)]
