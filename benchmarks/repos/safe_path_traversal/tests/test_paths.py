import pytest
from app.paths import safe_join


def test_parent_traversal_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(root, "../secret.txt")
