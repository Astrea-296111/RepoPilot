from more_itertools import locate, replace

def test_no_sentinel():
    assert list(locate([1,2],lambda *xs:sum(xs)>0,window_size=3)) == [0]
    assert list(replace([1,2],lambda *xs:sum(xs)>0,[9],window_size=3)) == [9]
