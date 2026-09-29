from app.text import slugify


def test_punctuation_and_edges_are_normalized():
    assert slugify("--Hello, Python!!--") == "hello-python"
    assert slugify("A__B  C") == "a-b-c"
