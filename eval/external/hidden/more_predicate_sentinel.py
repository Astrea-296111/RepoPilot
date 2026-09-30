import pytest
from more_itertools import locate, replace

@pytest.mark.parametrize('items,size', [([1],3),([1,2],3),([1,2,3],2),([1,2,3],1)])
def test_pred_values(items,size):
    seen=[]
    def pred(*xs):
        assert all(isinstance(x,int) for x in xs)
        seen.append(xs)
        return False
    list(locate(items,pred,window_size=size))
    assert list(replace(items,pred,[9],window_size=size)) == items

def test_none_and_limit():
    assert list(locate([None],lambda *xs:xs==(None,),window_size=2)) == [0]
    assert list(replace([1,2,3,4],lambda *xs:True,[8],count=1,window_size=2)) == [8,3,4]
    assert list(replace([1,2],lambda *xs:True,[8],count=0,window_size=3)) == [1,2]
