from app.config import resolve_timeout


def test_environment_timeout_overrides_config():
    assert resolve_timeout(30, {"timeout": 20}, {"APP_TIMEOUT": "10"}) == 10
