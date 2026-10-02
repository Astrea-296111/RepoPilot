"""Shared protocol boundary; policy and file operations remain in tools/."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
from typing import Callable, Any

from repopilot.tools.base import Tool, Workspace
from repopilot.tools.shell import bounded_output

log = logging.getLogger(__name__)


def server(name: str) -> Any:
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise ValueError("MCP requires: pip install -e '.[mcp]'") from exc
    return MCPServer(name)


def execute(tool: Tool, args: dict, *, allowed: bool = True) -> str:
    from mcp.server.mcpserver.exceptions import ToolError
    try:
        if not allowed:
            raise ValueError("Server policy denies this mutation or command")
        result = tool.execute(args)
        result.output = bounded_output(result.output)
        log.info("mcp tool=%s ok=%s", tool.name, result.ok)
        return json.dumps(asdict(result), ensure_ascii=False)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        log.warning("mcp tool=%s rejected: %s", tool.name, type(exc).__name__)
        raise ToolError(bounded_output(str(exc), 1000)) from exc


def run(factory: Callable[..., Any]) -> None:
    parser = argparse.ArgumentParser(description="RepoPilot scoped MCP tool server")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--allow-shell", action="store_true")
    parser.add_argument("--executor", choices=["docker", "local"], default="docker")
    parser.add_argument("--image", default="repopilot-sandbox:dev")
    parser.add_argument("--protected-path", action="append", default=[])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)  # stderr only: stdout belongs to MCP
    try:
        workspace = Workspace(args.repo, tuple(args.protected_path))
        factory(workspace, allow_write=args.allow_write, allow_shell=args.allow_shell,
                executor=args.executor, image=args.image).run(transport="stdio")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"MCP configuration error: {exc}\n")
