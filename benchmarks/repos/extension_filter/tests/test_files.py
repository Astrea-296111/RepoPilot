from app.files import filter_files


def test_extension_match_is_case_insensitive():
    assert filter_files(["a.py", "b.PY", "c.txt"], ".py") == ["a.py", "b.PY"]
