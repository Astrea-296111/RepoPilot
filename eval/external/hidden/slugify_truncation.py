import pytest
from slugify import slugify

@pytest.mark.parametrize('replacement', ['one--two','-one-two-','one---two'])
@pytest.mark.parametrize('separator', ['-','::',''])
@pytest.mark.parametrize('boundary,order', [(False,False),(False,True),(True,False),(True,True)])
def test_fitting(replacement,separator,boundary,order):
    expected=replacement.replace('-',separator)
    for limit in [len(expected),len(expected)+10]:
        assert slugify('x',algorithm='modern',allow_unicode=True,replacements=[('x',replacement)],replacement_stage='post',separator=separator,max_length=limit,word_boundary=boundary,save_order=order) == expected

def test_actual_truncation_and_legacy():
    assert slugify('a b c',algorithm='modern',separator='::',max_length=3) == 'a'
    assert slugify('Hello World') == 'hello-world'
