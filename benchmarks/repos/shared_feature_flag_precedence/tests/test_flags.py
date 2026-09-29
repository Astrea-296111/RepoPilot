from app.web import feature_enabled
from app.jobs import job_feature_enabled


def test_environment_overrides_config_for_web_and_jobs():
    config = {"NEW_UI": False}
    env = {"NEW_UI": " true "}
    assert feature_enabled(False, config, env, "NEW_UI")
    assert job_feature_enabled(False, config, env, "NEW_UI")
