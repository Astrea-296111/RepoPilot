import itertools
import pytest
from more_itertools import nth_combination_with_replacement as nth

@pytest.mark.parametrize('pool,r', [('',0),('',1),('a',4),('ab',3),('abc',2),('abc',0)])
def test_indexing(pool,r):
    expected=list(itertools.combinations_with_replacement(pool,r))
    for i,value in enumerate(expected):
        assert nth(iter(pool),r,i) == value
        assert nth(pool,r,i-len(expected)) == value
    for i in [len(expected),-len(expected)-1]:
        with pytest.raises(IndexError): nth(pool,r,i)

def test_negative_r():
    with pytest.raises(ValueError): nth('ab',-1,0)
