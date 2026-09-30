import pytest
from more_itertools import nth_permutation

def test_empty_permutation_set():
    with pytest.raises(IndexError): nth_permutation('abc',5,0)
