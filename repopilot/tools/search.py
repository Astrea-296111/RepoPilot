"""Bounded literal search with line numbers."""
from __future__ import annotations
from .base import ToolResult, Workspace
from repopilot.context.repo_map import iter_source_files, MAX_FILE_BYTES


class SearchCode:
    name = "search_code"
    description = "Literal case-insensitive text search under a workspace path"

    def __init__(self, workspace: Workspace): self.workspace = workspace

    def execute(self, args: dict) -> ToolResult:
        query = args["query"]
        if not isinstance(query, str) or not 1 <= len(query) <= 100:
            raise ValueError("搜索词长度必须在 1 到 100 字符之间")
        target = self.workspace.resolve(args.get("path", "."))
        if target.is_file() and target.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("搜索文件超过 512 KB 限制")
        files = [target] if target.is_file() else iter_source_files(target, 1000)
        matches = []
        for file in files:
            for number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append(f"{file.relative_to(self.workspace.root)}:{number}: {line[:240]}")
                    if len(matches) >= 80:
                        return ToolResult(True, "\n".join(matches)[:12000] + "\n[results truncated]")
        return ToolResult(True, "\n".join(matches) or "No matches")
