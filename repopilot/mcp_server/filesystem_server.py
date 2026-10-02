"""Scoped filesystem MCP tools; writes require explicit server permission."""
from __future__ import annotations

from typing import Any
from repopilot.tools.base import Workspace
from repopilot.tools.filesystem import ReadFile, WriteFile, ApplyPatch
from repopilot.tools.search import SearchCode
from .common import execute, run, server


def create_server(workspace: Workspace, *, allow_write: bool = False, **_: Any) -> Any:
    app = server("RepoPilot filesystem")

    @app.tool()
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read bounded numbered source lines inside the configured repository."""
        args = {"path": path, "start_line": start_line}
        if end_line is not None:
            args["end_line"] = end_line
        return execute(ReadFile(workspace), args)

    @app.tool()
    def search_code(query: str, path: str = ".") -> str:
        """Search bounded literal source text without running repository code."""
        return execute(SearchCode(workspace), {"query": query, "path": path})

    @app.tool()
    def write_file(path: str, content: str) -> str:
        """Create a new file, subject to server write permission and protected paths."""
        return execute(WriteFile(workspace), {"path": path, "content": content}, allowed=allow_write)

    @app.tool()
    def apply_patch(path: str, old_text: str, new_text: str) -> str:
        """Replace one exact occurrence; cannot write protected grading files."""
        return execute(ApplyPatch(workspace), {"path": path, "old_text": old_text, "new_text": new_text},
                       allowed=allow_write)

    return app


if __name__ == "__main__":
    run(create_server)
