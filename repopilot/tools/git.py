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
        # A real filename such as ':(top)' must not become Git pathspec magic
        # and escape a nested workspace. Keep only our exclusion patterns magic.
        rel = ":(literal)" + target.relative_to(self.workspace.root).as_posix()
        chunks = []
        # Read-only callers must not execute repository-configured diff/textconv/fsmonitor helpers.
        base = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-C", str(self.workspace.root)]
        exclusions = [":(exclude).env", ":(exclude)**/.env", ":(exclude).repopilot/**",
                      ":(exclude)**/.repopilot/**"]
        for prefix in (["diff", "--no-ext-diff", "--no-textconv", "--", rel, *exclusions],
                       ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--", rel, *exclusions]):
            proc = subprocess.run([*base, *prefix], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if proc.returncode:
                return ToolResult(False, bounded_output(proc.stderr or "git diff failed: initialize a Git repository"), proc.returncode)
            chunks.append(proc.stdout)
        # Git ignores untracked files in diff; report them explicitly so they aren't invisible.
        untracked = subprocess.run([*base, "ls-files", "--others", "--exclude-standard", "--", rel, *exclusions], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        if untracked.returncode:
            return ToolResult(False, bounded_output(untracked.stderr), untracked.returncode)
        if untracked.stdout:
            chunks.append("Untracked files (contents not included):\n" + untracked.stdout)
        return ToolResult(True, bounded_output("\n".join(chunks)) or "No changes")
