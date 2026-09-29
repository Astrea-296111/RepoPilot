from app.files import filter_files


def test_extension_without_dot_is_supported():
    assert filter_files(["a.Py", "b.txt", "c.py"], "py") == ["a.Py", "c.py"]
