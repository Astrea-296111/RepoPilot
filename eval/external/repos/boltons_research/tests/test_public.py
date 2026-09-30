from boltons.iterutils import research

def test_shared():
    item=('hello',)
    tree={'a':item,'b':item}
    paths=[p for p,v in research(tree) if v=='hello']
    assert paths == [('a',0),('b',0)]
