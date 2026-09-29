from pathlib import Path
from app.exporter import export_path


def test_exporter_uses_config_directory_and_absolute_paths_stay_absolute(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config_file = config_dir / "settings.toml"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert export_path(str(config_file), "exports/result.json") == (config_dir / "exports/result.json").resolve()
    absolute = (tmp_path / "absolute.txt").resolve()
    assert export_path(str(config_file), str(absolute)) == absolute
