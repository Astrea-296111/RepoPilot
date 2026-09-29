from pathlib import Path


def safe_join(root: str | Path, user_path: str) -> Path:
    root = Path(root).resolve()
    return (root / user_path).resolve()
