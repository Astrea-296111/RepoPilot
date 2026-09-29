from app.audit import same_actor


def test_audit_uses_same_normalization():
    assert same_actor("  Admin  ", "admin")
    assert same_actor("STRASSE", "straße")
