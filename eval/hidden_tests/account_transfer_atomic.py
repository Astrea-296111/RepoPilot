import pytest
from app.accounts import Accounts
from app.service import transfer


def test_valid_transfer_moves_money():
    accounts = Accounts({"a": 10, "b": 2})
    transfer(accounts, "a", "b", 4)
    assert accounts.balances == {"a": 6, "b": 6}


def test_non_positive_amount_does_not_mutate():
    accounts = Accounts({"a": 10, "b": 2})
    with pytest.raises(ValueError):
        transfer(accounts, "a", "b", 0)
    assert accounts.balances == {"a": 10, "b": 2}
