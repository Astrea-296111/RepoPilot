from app.reports import report_total


def test_report_uses_same_half_up_policy():
    assert report_total(1.005) == 1.01
    assert report_total(8.675) == 8.68
