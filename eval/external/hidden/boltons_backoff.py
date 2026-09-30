import pytest
from itertools import islice
from boltons.iterutils import backoff, backoff_iter

@pytest.mark.parametrize('start', [1,2.5,10])
def test_equal(start):
    assert backoff(start,start,factor=1) == [float(start)]

@pytest.mark.parametrize('start,stop', [(0,10),(1,8),(2,9)])
def test_cannot_grow(start,stop):
    with pytest.raises(ValueError): backoff(start,stop,factor=1)

@pytest.mark.parametrize('count', [0,1,4])
def test_count(count):
    assert backoff(2,8,count=count,factor=1) == [2.0]*count

def test_repeat_and_growth():
    assert list(islice(backoff_iter(2,8,count='repeat',factor=1),3)) == [2.0]*3
    assert backoff(1,8) == [1.0,2.0,4.0,8.0]
