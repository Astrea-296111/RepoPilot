"""Explainable filename + symbol + keyword file ranking."""
from __future__ import annotations
from pathlib import Path
import re
from .repo_map import FileEntry, MAX_FILE_BYTES

TRANSLATIONS = {
    "邮箱": ["email", "mail"], "重复": ["duplicate", "unique", "already"],
    "注册": ["register", "signup", "user"], "测试": ["test", "pytest"],
    "失败": ["fail", "error"], "用户": ["user"], "错误": ["error", "exception"],
}


def task_terms(task: str) -> set[str]:
    terms = {s.lower() for s in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", task) if len(s) >= 3}
    for chinese, english in TRANSLATIONS.items():
        if chinese in task:
            terms.update(english)
    return terms


def retrieve(root: Path, entries: list[FileEntry], task: str, top_k: int = 5) -> list[tuple[str, int]]:
    terms = task_terms(task)
    scored = []
    for entry in entries:
        path = root / entry.path
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        source = path.read_text(encoding="utf-8", errors="replace").lower()
        name = entry.path.lower()
        symbols = " ".join(entry.symbols).lower()
        score = sum(6 if word in name else 0 for word in terms)
        score += sum(4 if word in symbols else 0 for word in terms)
        score += sum(min(source.count(word), 5) for word in terms)
        if score:
            scored.append((entry.path, score))
    return sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]

