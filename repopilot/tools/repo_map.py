"""Bounded, read-only repository map using the shared workspace boundary."""
from repopilot.context.repo_map import build_repo_map, render_repo_map
from .base import ToolResult, Workspace
from .shell import bounded_output


class RepoMap:
    name = "repo_map"
    description = "List source files, Python symbols and imports without executing code"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def execute(self, args: dict) -> ToolResult:
        target = self.workspace.resolve(args.get("path", "."))
        if not target.is_dir():
            raise ValueError("repo_map path must be a directory inside the workspace")
        max_files = args.get("max_files", 1000)
        if not isinstance(max_files, int) or not 1 <= max_files <= 1000:
            raise ValueError("max_files must be between 1 and 1000")
        return ToolResult(True, bounded_output(render_repo_map(build_repo_map(target, max_files))))
