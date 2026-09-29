import pytest
from app.users import DuplicateEmailError, UserService


def test_duplicate_email_hidden_preserves_normal_flow():
    service = UserService()
    assert service.register("a@example.com", "pw") == "a@example.com"
    assert service.register("b@example.com", "pw") == "b@example.com"
    with pytest.raises(DuplicateEmailError):
        service.register("a@example.com", "other")
