from slugify import slugify

def test_uppercase():
    assert slugify('&#X41;',algorithm='modern') == 'a'
