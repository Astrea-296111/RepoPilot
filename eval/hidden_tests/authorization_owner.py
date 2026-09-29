from app.auth import can_edit


def test_owner_can_edit_without_admin_role():
    assert can_edit("u1", "u1", "member") is True


def test_unrelated_member_cannot_edit():
    assert can_edit("u2", "u1", "member") is False
