"""Intentionally broken tiny registration service for the demo."""


class DuplicateEmailError(Exception):
    """Raised when an email address is already registered."""


class UserService:
    def __init__(self):
        self.users: dict[str, str] = {}

    def register(self, email: str, password: str) -> str:
        """Register a new account and return its email."""
        if email in self.users:
            # BUG: a storage implementation detail leaks to callers.
            raise ValueError('UNIQUE constraint failed: users.email')
        self.users[email] = password
        return email
