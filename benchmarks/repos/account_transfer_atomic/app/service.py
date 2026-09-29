from .accounts import Accounts


class InsufficientFunds(RuntimeError):
    pass


def transfer(accounts: Accounts, source: str, target: str, amount: int) -> None:
    accounts.debit(source, amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    if accounts.get(source) < 0:
        raise InsufficientFunds(source)
    accounts.credit(target, amount)
