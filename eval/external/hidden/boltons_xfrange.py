import pytest
from boltons.iterutils import xfrange, frange

@pytest.mark.parametrize('start,stop,step', [(0,1,.1),(0,10,.1),(1,3,.75),(6,-2,-.5),(1,5,-1),(5,0,1),(0,0,1),(-2,2,.3)])
def test_matches(start,stop,step):
    assert list(xfrange(start,stop,step)) == frange(start,stop,step)

def test_zero():
    with pytest.raises(ValueError): list(xfrange(2,step=0))
