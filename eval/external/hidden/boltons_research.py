from boltons.iterutils import research, remap

def test_multiple_paths():
    shared=(7,)
    tree={'left':[shared], 'right':shared}
    assert [p for p,v in research(tree,lambda p,k,v:isinstance(v,int))] == [('left',0,0),('right',0)]

def test_remap_keeps_identity():
    shared=[1,2]
    mapped=remap({'a':shared,'b':shared})
    assert mapped['a'] is mapped['b']

def test_filter_and_errors():
    assert research({'a':[1,2]}, lambda p,k,v:v==2) == [(('a',1),2)]
    assert research({'a':1},lambda p,k,v:1/0) == []
