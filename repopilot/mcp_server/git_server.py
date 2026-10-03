"""Git inspection over MCP, without shell interpolation or configured diff helpers."""
from __future__ import annotations
from typing import Any
from repopilot.tools.base import Workspace
from repopilot.tools.git import GitDiff, GitStatus
from .common import execute, run, server


def create_server(workspace: Workspace, **_: Any) -> Any:
    app = server("RepoPilot git")

    @app.tool()
    def git_diff(path: str = ".") -> str:
        """Return staged and unstaged diff within the repository boundary."""
        return execute(GitDiff(workspace), {"path": path})

    @app.tool()
    def git_status(path: str = ".") -> str:
        """Return bounded porcelain status within the repository boundary."""
        return execute(GitStatus(workspace), {"path": path})

    return app


if __name__ == "__main__":
    run(create_server)
