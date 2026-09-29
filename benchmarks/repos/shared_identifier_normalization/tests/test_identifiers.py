from app.login import same_login
from app.api_keys import same_owner


def test_login_and_owner_ignore_spaces_and_case():
    assert same_login("Alice", " alice ")
    assert same_owner("STRASSE", " straße ")
