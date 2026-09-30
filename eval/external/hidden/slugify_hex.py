import pytest
from slugify import slugify

@pytest.mark.parametrize('prefix', ['x','X'])
def test_decode(prefix):
    assert slugify(f'&#{prefix}41; &#{prefix}e9;',algorithm='modern',allow_unicode=True) == 'a-é'
    assert slugify(f'&#{prefix}41;',algorithm='modern',lowercase=False) == 'A'

def test_compatibility():
    assert slugify('&#X41;') == 'x41'
    assert slugify('&#X41;',algorithm='legacy') == 'x41'
    assert slugify('&#X41;',algorithm='modern',hexadecimal=False) == 'x41'

@pytest.mark.parametrize('bad', ['110000','D800'])
def test_invalid_neighbor(bad):
    assert slugify(f'&#X{bad}; &#X41;',algorithm='modern') == 'x'+bad.lower()+'-a'
