from app.parser import parse_record


def test_preserves_declared_header_order():
    assert parse_record("name,email", "Ada,ada@example.com") == {"name": "Ada", "email": "ada@example.com"}
