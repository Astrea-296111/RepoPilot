from app.parser import parse_record


def test_three_columns_keep_positions():
    assert parse_record("z,a,m", "1,2,3") == {"z": "1", "a": "2", "m": "3"}
