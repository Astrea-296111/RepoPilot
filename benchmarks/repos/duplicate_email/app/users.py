class DuplicateEmailError(ValueError):
    pass


class UserService:
    def __init__(self):
        self._emails = set()

    def register(self, email: str, password: str) -> str:
        if email in self._emails:
            raise ValueError('UNIQUE constraint failed: users.email')
        self._emails.add(email)
        return email
