from app.users import normalize_username


def test_trims_and_lowercases_username():
    assert normalize_username("  Alice ") == "alice"
