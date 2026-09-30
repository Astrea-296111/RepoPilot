from boltons.iterutils import split

def test_zero():
    assert split([1,None,2],maxsplit=0) == [[1,None,2]]
