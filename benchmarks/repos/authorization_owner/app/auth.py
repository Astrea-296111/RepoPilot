def can_edit(user_id: str, owner_id: str, role: str) -> bool:
    return role == "admin" and user_id == owner_id
