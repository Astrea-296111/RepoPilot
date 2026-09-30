import pytest
from boltons.iterutils import split, split_iter

@pytest.mark.parametrize('value', [[],[1,None,2],[0,False],(1,2),'abc'])
def test_zero(value):
    assert split(value,maxsplit=0) == [list(value)]
    assert list(split_iter(iter(value),maxsplit=0)) == [list(value)]

def test_normal():
    assert split([1,None,2,None,3],maxsplit=1) == [[1],[2,None,3]]
    assert split([1,None,2]) == [[1],[2]]
