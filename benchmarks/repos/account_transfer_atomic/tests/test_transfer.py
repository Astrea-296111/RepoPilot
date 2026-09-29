import pytest
from app.accounts import Accounts
from app.service import InsufficientFunds, transfer


def test_insufficient_funds_do_not_mutate_accounts():
    accounts = Accounts({"a": 5, "b": 1})
    with pytest.raises(InsufficientFunds):
        transfer(accounts, "a", "b", 10)
    assert accounts.balances == {"a": 5, "b": 1}
