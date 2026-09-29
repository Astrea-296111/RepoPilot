from pathlib import Path
import pytest
from app.paths import safe_join


def test_absolute_escape_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    with pytest.raises(ValueError):
        safe_join(root, str(outside))


def test_nested_path_inside_root_is_allowed(tmp_path):
    root = tmp_path / "root"
    nested = root / "a" / "b.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("ok")
    assert safe_join(root, "a/b.txt") == nested.resolve()
