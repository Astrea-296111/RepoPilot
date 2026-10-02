"""AST-aligned, bounded code chunks with stable source locations."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import re

from .retrieval import task_terms


@dataclass
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    text: str
    symbols: list[str]

    @property
    def identity(self) -> str:
        return hashlib.sha256(f"{self.path}:{self.start_line}:{self.text}".encode()).hexdigest()


def tokenize(text: str) -> list[str]:
    """Split identifiers/camelCase and include Chinese characters plus demo aliases."""
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", " ")
    tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", split.lower())
    return tokens + sorted(task_terms(text))


def chunk_source(path: str, source: str, max_chars: int = 2400) -> list[CodeChunk]:
    lines = source.splitlines(keepends=True)
    boundaries = {0, len(lines)}
    definitions: list[tuple[int, int, str]] = []
    if path.endswith(".py"):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    begin = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
                    end = node.end_lineno or node.lineno
                    boundaries.update((begin, end))
                    definitions.append((begin, end, node.name))
    points = sorted(boundaries)
    chunks: list[CodeChunk] = []
    for left, right in zip(points, points[1:]):
        start = left
        current = ""
        for line_number in range(left, right):
            line = lines[line_number]
            if current and len(current) + len(line) > max_chars:
                names = [name for begin, end, name in definitions if begin <= start < end]
                chunks.append(CodeChunk(path, start + 1, line_number, current, names))
                start, current = line_number, ""
            # Split very long lines too; locations remain precise at line granularity.
            while len(line) > max_chars:
                names = [name for begin, end, name in definitions if begin <= line_number < end]
                chunks.append(CodeChunk(path, line_number + 1, line_number + 1, line[:max_chars], names))
                line = line[max_chars:]
            current += line
        if current.strip():
            names = [name for begin, end, name in definitions if begin <= start < end]
            chunks.append(CodeChunk(path, start + 1, right, current, names))
    return chunks
