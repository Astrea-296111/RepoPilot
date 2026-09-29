from app.cli import cli_feature_enabled


def test_cli_uses_same_precedence_and_config_beats_default():
    assert cli_feature_enabled(False, {"X": True}, {}, "X")
    assert not cli_feature_enabled(True, {"X": True}, {"X": "false"}, "X")
