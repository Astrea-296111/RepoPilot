from pathlib import Path
from app.cli import output_path
from app.worker import cache_path


def test_relative_paths_are_based_on_config_directory(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_file = config_dir / "app.toml"
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert output_path(str(config_file), "out/data.db") == (config_dir / "out/data.db").resolve()
    assert cache_path(str(config_file), "cache") == (config_dir / "cache").resolve()
