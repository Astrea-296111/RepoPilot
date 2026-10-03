"""One tool contract for direct Python calls and real MCP stdio sessions."""
from __future__ import annotations

from contextlib import ExitStack
import json
import logging
from pathlib import Path
import sys
from typing import Any, Protocol

from .base import Tool, ToolResult
from .shell import bounded_output

log = logging.getLogger(__name__)


class ToolBackend(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...
    def close(self) -> None: ...


class PythonToolBackend:
    def __init__(self, tools: dict[str, Tool]) -> None:
        self.tools = tools

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        return self.tools[name].execute(arguments)

    def close(self) -> None:
        pass


class MCPToolBackend:
    """Persistent SDK clients on a private async portal; close all subprocesses after a run.

    No automatic retries: a lost response after a mutation does not prove that it
    was not applied. The next agent decision must inspect repository evidence.
    """
    GROUPS = {"read_file": "filesystem", "write_file": "filesystem", "apply_patch": "filesystem",
              "search_code": "filesystem", "git_diff": "git", "git_status": "git", "run_command": "shell"}

    def __init__(self, root: Path, *, executor: str, image: str,
                 allow_mutation: bool, protected_paths: tuple[str, ...] = ()) -> None:
        try:
            import mcp  # noqa: F401
        except ImportError as exc:
            raise ValueError("MCP backend requires: pip install -e '.[mcp]'") from exc
        self.root, self.executor, self.image = root, executor, image
        self.allow_mutation, self.protected_paths = allow_mutation, protected_paths
        self._stack: ExitStack | None = None
        self._portal: Any = None
        self._clients: dict[str, Any] = {}

    def _client(self, group: str) -> Any:
        from anyio.from_thread import start_blocking_portal
        from mcp import Client, StdioServerParameters
        if self._stack is None:
            self._stack = ExitStack()
            self._portal = self._stack.enter_context(start_blocking_portal())
        if group not in self._clients:
            args = ["-m", f"repopilot.mcp_server.{group}_server", str(self.root),
                    "--executor", self.executor, "--image", self.image]
            if self.allow_mutation:
                args += ["--allow-write", "--allow-shell"]
            for path in self.protected_paths:
                args += ["--protected-path", path]
            params = StdioServerParameters(command=sys.executable, args=args)
            client = Client(params, read_timeout_seconds=145)
            self._clients[group] = self._stack.enter_context(self._portal.wrap_async_context_manager(client))
            log.info("mcp connected group=%s", group)
        return self._clients[group]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in self.GROUPS:
            return ToolResult(False, "Unknown MCP tool: " + name)
        try:
            client = self._client(self.GROUPS[name])
            response = self._portal.call(client.call_tool, name, arguments)
            content = "\n".join(item.text for item in response.content if hasattr(item, "text"))
            if response.is_error:
                return ToolResult(False, bounded_output(content))
            data = json.loads(content)
            if not isinstance(data, dict) or type(data.get("ok")) is not bool or not isinstance(data.get("output"), str):
                raise ValueError("Invalid MCP ToolResult")
            return ToolResult(**data)
        except Exception as exc:
            log.warning("mcp call failed tool=%s error=%s", name, type(exc).__name__)
            return ToolResult(False, f"MCP {type(exc).__name__}: {bounded_output(str(exc), 1000)}")

    def close(self) -> None:
        try:
            if self._stack is not None:
                self._stack.close()
        finally:
            self._stack, self._portal = None, None
            self._clients.clear()
