"""Scan a repository and extract compact Python symbols without executing code."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re

SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "build", ".repopilot", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".md", ".toml", ".yaml", ".yml", ".json", ".txt"}
MAX_FILE_BYTES = 512_000


@dataclass
class FileEntry:
    path: str
    imports: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)


def iter_source_files(root: Path, max_files: int = 4000):
    """Yield bounded text files; skip hidden/build trees and all symlinks."""
    root = root.resolve()
    count = 0
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        with path.open("rb") as stream:
            if b"\0" in stream.read(4096):
                continue
        yield path
        count += 1
        if count >= max_files:
            break


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    names = [a.arg for a in args.posonlyargs + args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    annotated = []
    lookup = {a.arg: a for a in args.posonlyargs + args.args + args.kwonlyargs}
    for name in names:
        item = lookup.get(name)
        annotation = ast.unparse(item.annotation) if item and item.annotation else ""
        annotated.append(name + (": " + annotation if annotation else ""))
    ret = " -> " + ast.unparse(node.returns) if node.returns else ""
    return f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}({', '.join(annotated)}){ret}"


def build_repo_map(root: Path, max_files: int = 4000) -> list[FileEntry]:
    entries = []
    for path in iter_source_files(root, max_files):
        entry = FileEntry(path.relative_to(root.resolve()).as_posix())
        source = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".py":
            try:
                tree = ast.parse(source)
            except SyntaxError:
                entry.symbols.append("[syntax error: AST unavailable]")
            else:
                for node in tree.body:
                    if isinstance(node, ast.Import):
                        entry.imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        entry.imports.append(node.module or ".")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        entry.symbols.append(_signature(node))
                        if ast.get_docstring(node):
                            entry.symbols.append("  doc: " + ast.get_docstring(node).splitlines()[0][:100])
                    elif isinstance(node, ast.ClassDef):
                        entry.symbols.append("class " + node.name)
                        for method in node.body:
                            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                entry.symbols.append("  " + _signature(method))
        elif path.suffix in {".js", ".ts", ".java", ".go", ".rs"}:
            entry.symbols = re.findall(r"(?m)^\s*(?:export\s+)?(?:function|class|interface|func|struct)\s+[A-Za-z_]\w*", source)[:30]
        entries.append(entry)
    return entries


def render_repo_map(entries: list[FileEntry], max_chars: int = 12000) -> str:
    lines = []
    for entry in entries:
        lines.append(entry.path)
        lines.extend("  import " + item for item in entry.imports[:8])
        lines.extend("  " + item for item in entry.symbols[:25])
    joined = "\n".join(lines)
    return joined[:max_chars] + ("\n[map truncated]" if len(joined) > max_chars else "")

