from boltons.iterutils import backoff

def test_equal():
    assert backoff(5,5,factor=1.0) == [5.0]
