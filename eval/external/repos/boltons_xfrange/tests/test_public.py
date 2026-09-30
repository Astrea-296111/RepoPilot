from boltons.iterutils import xfrange, frange

def test_descending():
    assert list(xfrange(5, 0, step=-1.25)) == frange(5, 0, step=-1.25)
