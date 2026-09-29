from app.http_client import should_retry_request
from app.uploader import should_retry_upload


def test_429_and_5xx_retry_but_400_does_not():
    assert should_retry_request(429)
    assert should_retry_upload(503)
    assert not should_retry_request(400)
