"""Shared tool contract, result shape and workspace boundary checks."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class ToolResult:
    ok: bool
    output: str
    exit_code: int | None = None
    changed_file: str | None = None


class Tool(Protocol):
    name: str
    description: str

    def execute(self, args: dict[str, Any]) -> ToolResult: ...


class Workspace:
    def __init__(self, root: Path, protected_paths: tuple[str, ...] = ()):
        self.root = root.resolve(strict=True)
        self.protected_paths = tuple((self.root / p).resolve() for p in protected_paths)
        if not self.root.is_dir():
            raise ValueError("仓库路径必须是目录")

    def resolve(self, relative: str, *, exists: bool = True) -> Path:
        if not isinstance(relative, str) or not relative or "\0" in relative:
            raise ValueError("文件路径无效")
        path = (self.root / relative).resolve(strict=False)
        if not path.is_relative_to(self.root):
            raise ValueError("拒绝访问仓库外部的路径")
        if any(part in {".git", ".repopilot"} for part in path.relative_to(self.root).parts):
            raise ValueError("拒绝访问仓库的内部管理目录")
        if path.name == ".env":
            raise ValueError("拒绝通过文件工具读取或修改 .env")
        if exists and not path.exists():
            raise ValueError("目标路径不存在")
        return path

    def writable(self, path: Path) -> None:
        if any(path == p or path.is_relative_to(p) for p in self.protected_paths):
            raise ValueError("拒绝修改受保护的评分文件")
