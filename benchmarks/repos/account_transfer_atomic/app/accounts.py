class Accounts:
    def __init__(self, balances: dict[str, int]):
        self.balances = dict(balances)

    def get(self, account: str) -> int:
        return self.balances.get(account, 0)

    def debit(self, account: str, amount: int) -> None:
        self.balances[account] = self.get(account) - amount

    def credit(self, account: str, amount: int) -> None:
        self.balances[account] = self.get(account) + amount
