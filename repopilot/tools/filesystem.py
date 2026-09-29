"""Small file reads and exact single-occurrence text patches."""
from __future__ import annotations
import difflib
import os
import tempfile
from .base import ToolResult, Workspace


class ReadFile:
    name = "read_file"
    description = "Read numbered lines of a workspace file"

    def __init__(self, workspace: Workspace): self.workspace = workspace

    def execute(self, args: dict) -> ToolResult:
        path = self.workspace.resolve(args["path"])
        if not path.is_file() or path.stat().st_size > 512_000:
            raise ValueError("只能读取不超过 512 KB 的文件")
        start = int(args.get("start_line", 1))
        end = int(args.get("end_line", start + 119))
        if start < 1 or end < start or end - start > 299:
            raise ValueError("行号范围必须为 1 到 300 行")
        lines = path.read_text(encoding="utf-8").splitlines()
        return ToolResult(True, "\n".join(f"{i}: {lines[i-1]}" for i in range(start, min(end, len(lines)) + 1)))


class ApplyPatch:
    name = "apply_patch"
    description = "Replace exactly one old text occurrence with new text"

    def __init__(self, workspace: Workspace): self.workspace = workspace

    def execute(self, args: dict) -> ToolResult:
        path = self.workspace.resolve(args["path"])
        if not path.is_file() or path.stat().st_size > 512_000:
            raise ValueError("只能修改不超过 512 KB 的已有文件")
        old, new = args["old_text"], args["new_text"]
        if not isinstance(old, str) or not old or not isinstance(new, str) or len(new) > 128_000:
            raise ValueError("补丁内容不合法或过长")
        before = path.read_text(encoding="utf-8")
        if before.count(old) != 1:
            raise ValueError("old_text 必须在目标文件中恰好出现一次")
        after = before.replace(old, new, 1)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(after)
            temporary = handle.name
        try:
            os.chmod(temporary, path.stat().st_mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=args["path"], tofile=args["path"]))
        return ToolResult(True, diff[:8000], changed_file=args["path"])


class WriteFile:
    name = "write_file"
    description = "Create a small new file; never overwrite an existing file"

    def __init__(self, workspace: Workspace): self.workspace = workspace

    def execute(self, args: dict) -> ToolResult:
        path = self.workspace.resolve(args["path"], exists=False)
        content = args["content"]
        if path.exists() or not path.parent.is_dir() or not isinstance(content, str) or len(content) > 128_000:
            raise ValueError("只能在已有目录创建不超过 128 KB 的新文件")
        with path.open("x", encoding="utf-8") as stream: stream.write(content)
        return ToolResult(True, "Created " + args["path"], changed_file=args["path"])
