from slugify import slugify

def test_fits():
    assert slugify('x',algorithm='modern',allow_unicode=True,replacements=[('x','one--two')],replacement_stage='post',word_boundary=True,max_length=20) == 'one--two'
