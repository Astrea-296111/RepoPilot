from app.merge import deep_merge


def test_scalar_override_replaces_dict_and_inputs_unchanged():
    base = {"a": {"b": 1}, "x": 1}
    override = {"a": 5}
    result = deep_merge(base, override)
    assert result == {"a": 5, "x": 1}
    assert base == {"a": {"b": 1}, "x": 1}


def test_multiple_nested_levels_merge():
    assert deep_merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"d": 3}}}) == {"a": {"b": {"c": 1, "d": 3}}}
