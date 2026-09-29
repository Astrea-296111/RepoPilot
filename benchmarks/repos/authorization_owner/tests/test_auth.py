from app.auth import can_edit


def test_admin_can_edit_other_users_resource():
    assert can_edit("admin-1", "user-1", "admin") is True
