from app.users import DuplicateEmailError, UserService
import pytest


def test_duplicate_email():
    service = UserService()
    service.register("a@example.com", "pw")
    with pytest.raises(DuplicateEmailError):
        service.register("a@example.com", "pw2")

