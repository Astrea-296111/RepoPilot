"""Show a bounded Git diff from the target checkout."""
from __future__ import annotations
import subprocess
from .base import ToolResult, Workspace
from .shell import bounded_output


class GitDiff:
    name = "git_diff"
    description = "Show unstaged and staged Git changes under the workspace"

    def __init__(self, workspace: Workspace): self.workspace = workspace

    def execute(self, args: dict) -> ToolResult:
        path = args.get("path", ".")
        target = self.workspace.resolve(path)
        rel = target.relative_to(self.workspace.root).as_posix()
        # -C root keeps the checkout's subdirectory scope even when root is nested.
        chunks = []
        for prefix in (["diff", "--", rel], ["diff", "--cached", "--", rel]):
            proc = subprocess.run(["git", "-C", str(self.workspace.root), *prefix], capture_output=True, text=True, timeout=10)
            if proc.returncode:
                return ToolResult(False, bounded_output(proc.stderr or "git diff failed: initialize a Git repository"), proc.returncode)
            chunks.append(proc.stdout)
        # Git ignores untracked files in diff; report them explicitly so they aren't invisible.
        untracked = subprocess.run(["git", "-C", str(self.workspace.root), "ls-files", "--others", "--exclude-standard", "--", rel], capture_output=True, text=True, timeout=10)
        if untracked.stdout:
            chunks.append("Untracked files (contents not included):\n" + untracked.stdout)
        return ToolResult(True, bounded_output("\n".join(chunks)) or "No changes")
