from app.config import resolve_timeout


def test_config_then_default_fallbacks():
    assert resolve_timeout(30, {"timeout": 12}, {}) == 12
    assert resolve_timeout(30, {}, {}) == 30


def test_environment_wins_even_when_config_exists():
    assert resolve_timeout(30, {"timeout": 12}, {"APP_TIMEOUT": "7"}) == 7
