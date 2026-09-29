from app.merge import deep_merge


def test_nested_dicts_are_merged():
    base = {"db": {"host": "localhost", "port": 5432}, "debug": False}
    override = {"db": {"port": 6432}}
    assert deep_merge(base, override) == {"db": {"host": "localhost", "port": 6432}, "debug": False}
