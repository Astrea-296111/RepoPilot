from app.text import slugify


def test_collapses_multiple_spaces():
    assert slugify("Hello   World") == "hello-world"
