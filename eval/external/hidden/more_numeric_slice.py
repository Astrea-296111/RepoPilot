from decimal import Decimal
import pytest
from more_itertools import numeric_range

@pytest.mark.parametrize('params', [(0,10,2),(10,0,-2),(0,0,1),(-4,5,3)])
@pytest.mark.parametrize('sl', [slice(None,None,-1),slice(None,None,-2),slice(3,0,-1),slice(-1,-8,-2),slice(-100,100,1),slice(100,-100,-1),slice(1,4,1)])
def test_range(params,sl):
    r=numeric_range(*params)
    assert list(r[sl]) == list(range(*params))[sl]

def test_decimal():
    r=numeric_range(Decimal('0'),Decimal('1'),Decimal('.2'))
    assert list(r[::-1]) == list(r)[::-1]

def test_zero_slice():
    with pytest.raises(ValueError): numeric_range(4)[::0]
