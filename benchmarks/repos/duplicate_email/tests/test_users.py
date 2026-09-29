import pytest
from app.users import DuplicateEmailError, UserService


def test_duplicate_email_uses_domain_exception():
    service = UserService()
    service.register("a@example.com", "pw")
    with pytest.raises(DuplicateEmailError):
        service.register("a@example.com", "pw2")
