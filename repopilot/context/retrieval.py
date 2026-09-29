"""Explainable filename + symbol + keyword file ranking."""
from __future__ import annotations
from collections import Counter
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


def _local_imports(entries: list[FileEntry]) -> dict[str, set[str]]:
    """Resolve Python imports to files inside this repository; ignore external modules."""
    modules = {}
    for entry in entries:
        if not entry.path.endswith(".py"):
            continue
        module = entry.path[:-3].replace("/", ".")
        if module.endswith(".__init__"):
            module = module[:-9]
        modules[module] = entry.path

    edges = {}
    for entry in entries:
        if not entry.path.endswith(".py"):
            continue
        importer = entry.path[:-3].replace("/", ".")
        package = importer if importer.endswith(".__init__") else importer.rpartition(".")[0]
        if package.endswith(".__init__"):
            package = package[:-9]
        targets = set()
        for item in entry.imports:
            level = len(item) - len(item.lstrip("."))
            if level:
                parts = package.split(".") if package else []
                if level > len(parts):
                    continue
                prefix = parts[:len(parts) - level + 1]
                name = ".".join(prefix + ([item[level:]] if item[level:] else []))
            else:
                name = item
            target = modules.get(name)
            if target and target != entry.path:
                targets.add(target)
        edges[entry.path] = targets
    return edges


def retrieve_with_imports(root: Path, entries: list[FileEntry], task: str,
                          top_k: int = 5) -> list[tuple[str, int]]:
    """Keep strong lexical matches, then reserve slots for their local dependencies.

    When the task has no lexical matches, use source import in-degree to expose
    shared implementation files. The returned score denotes lexical relevance or
    the number of source files that import the candidate.
    """
    if top_k <= 0:
        return []
    lexical = retrieve(root, entries, task, top_k=top_k)
    edges = _local_imports(entries)
    centrality = Counter(target for source, targets in edges.items()
                         if not source.startswith("tests/")
                         for target in targets)
    anchors = lexical[:min(2, top_k)]
    output = list(anchors)
    seen = {path for path, _ in output}
    if anchors:
        related = set().union(*(edges.get(path, set()) for path, _ in anchors))
        candidates = sorted(related - seen, key=lambda path: (-centrality[path], path))
    else:
        candidates = sorted(centrality, key=lambda path: (-centrality[path], path))
    for path in candidates:
        if len(output) >= top_k:
            break
        output.append((path, centrality[path]))
        seen.add(path)
    for path, score in lexical:
        if len(output) >= top_k:
            break
        if path not in seen:
            output.append((path, score))
            seen.add(path)
    return output
