"""Official MCP SDK v2 stdio server exposing only existing read-only policies."""
from pathlib import Path
from typing import Annotated

from pydantic import Field

from repopilot.tools.base import Workspace
from repopilot.tools.filesystem import ReadFile
from repopilot.tools.git import GitDiff
from repopilot.tools.repo_map import RepoMap
from repopilot.tools.search import SearchCode
from repopilot.tools.shell import bounded_output


def create_server(repo: Path):
    """Create a read-only server rooted at one explicit, valid repository directory.

    Import the optional SDK only when requested. No session directory is created,
    no model is called, and no shell or mutation tool is registered.
    """
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise ValueError("MCP server requires: pip install -e '.[mcp]' (from the RepoPilot checkout)") from exc
    workspace = Workspace(repo)
    tools = {tool.name: tool for tool in (RepoMap(workspace), ReadFile(workspace),
                                         SearchCode(workspace), GitDiff(workspace))}
    server = MCPServer("RepoPilot", instructions="Read-only tools for one repository. Paths stay inside its root.")
    readonly = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                               idempotent_hint=True, open_world_hint=False)

    def execute(name: str, args: dict) -> str:
        try:
            result = tools[name].execute(args)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise ToolError(bounded_output(str(exc), 500)) from exc
        if not result.ok:
            raise ToolError(bounded_output(result.output, 1000))
        return bounded_output(result.output)

    @server.tool(annotations=readonly)
    def repo_map(path: str = ".", max_files: Annotated[int, Field(ge=1, le=1000)] = 1000) -> str:
        """Return a bounded AST file, symbol and import map without running source code."""
        return execute("repo_map", {"path": path, "max_files": max_files})

    @server.tool(annotations=readonly)
    def search_code(query: Annotated[str, Field(min_length=1, max_length=100)], path: str = ".") -> str:
        """Search literal text inside the root; at most 80 matches and 12000 characters."""
        return execute("search_code", {"query": query, "path": path})

    @server.tool(annotations=readonly)
    def read_file(path: str, start_line: Annotated[int, Field(ge=1)] = 1,
                  end_line: Annotated[int, Field(ge=1)] | None = None) -> str:
        """Read up to 300 numbered lines of a file no larger than 512 KB."""
        args = {"path": path, "start_line": start_line}
        if end_line is not None:
            args["end_line"] = end_line
        return execute("read_file", args)

    @server.tool(annotations=readonly)
    def git_diff(path: str = ".") -> str:
        """Read a bounded Git diff; report a protocol tool error for a non-Git root."""
        return execute("git_diff", {"path": path})

    return server


def main():
    """Run the stdio server as `python -m repopilot.mcp_server REPO`."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    args = parser.parse_args()
    try:
        create_server(args.repo).run(transport="stdio")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"MCP configuration error: {exc}\n")


if __name__ == "__main__":
    main()
