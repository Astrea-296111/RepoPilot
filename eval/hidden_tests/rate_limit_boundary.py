from app.limits import check_limit


def test_inside_window_still_limits_and_above_boundary_resets():
    assert check_limit(109, 100, 5, 5, 10) == (False, 100, 5)
    assert check_limit(111, 100, 5, 5, 10) == (True, 111, 1)
