from app.limits import check_limit


def test_exact_window_boundary_resets():
    assert check_limit(110, 100, 5, 5, 10) == (True, 110, 1)
