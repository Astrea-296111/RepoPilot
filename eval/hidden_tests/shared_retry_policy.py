from app.background import should_retry_background


def test_background_uses_same_shared_policy():
    assert should_retry_background(429)
    assert should_retry_background(500)
    assert not should_retry_background(404)
