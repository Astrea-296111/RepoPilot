"""Select AST blocks by public task symbols, never by reference fix locations."""
from __future__ import annotations
import ast
from .retrieval import task_terms


def source_excerpt(source: str, task: str, max_chars: int = 6000) -> str:
    if len(source) <= max_chars:
        return source
    lines = source.splitlines(keepends=True)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source[:max_chars]
    terms = task_terms(task)
    definitions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    selected = [n for name,n in definitions.items() if name.lower() in terms]
    if not selected:
        return source[:max_chars]
    dependencies = {n.id for block in selected for n in ast.walk(block) if isinstance(n, ast.Name)}
    selected += [n for name,n in definitions.items() if name in dependencies and n not in selected]
    chunks=[]
    for node in selected:
        blocks=node.body if isinstance(node,ast.ClassDef) else [node]
        if isinstance(node,ast.ClassDef):
            chunks.append(f'CLASS {node.name}\n')
        for block in blocks:
            if isinstance(block,ast.Expr) and isinstance(block.value,ast.Constant) and isinstance(block.value.value,str):
                continue
            # Keep signature and implementation; long docstrings consume no budget.
            start=block.lineno-1
            if isinstance(block,(ast.FunctionDef,ast.AsyncFunctionDef)) and ast.get_docstring(block):
                doc=block.body[0]
                chunks.append(f'LINES {start+1}-{doc.lineno-1}\n'+''.join(lines[start:doc.lineno-1]))
                start=doc.end_lineno
            chunks.append(f'LINES {start+1}-{block.end_lineno}\n'+''.join(lines[start:block.end_lineno]))
    return ''.join(chunks)[:max_chars]
