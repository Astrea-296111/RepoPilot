import re


def slugify(text: str) -> str:
    cleaned = text.strip().lower().replace(" ", "-")
    return cleaned
