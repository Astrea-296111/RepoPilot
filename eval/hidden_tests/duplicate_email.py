from app.users import DuplicateEmailError, UserService


def test_duplicate_email_hidden_keeps_address_and_normal_flow():
    service = UserService()
    assert service.register("a@example.com", "pw") == "a@example.com"
    try:
        service.register("a@example.com", "other")
    except DuplicateEmailError as exc:
        assert "a@example.com" in str(exc)
    else:
        raise AssertionError("DuplicateEmailError was not raised")
