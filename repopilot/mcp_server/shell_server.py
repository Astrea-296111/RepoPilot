"""Timed shell MCP tool using the same Docker/local executor as Python tools."""
from __future__ import annotations
from typing import Any
from repopilot.tools.base import Workspace
from repopilot.tools.shell import LocalExecutor, RunCommand
from repopilot.sandbox.docker import DockerExecutor
from .common import execute, run, server


def create_server(workspace: Workspace, *, allow_shell: bool = False,
                  executor: str = "docker", image: str = "repopilot-sandbox:dev", **_: Any) -> Any:
    if executor not in {"local", "docker"}:
        raise ValueError("Invalid executor")
    protected = tuple(p.relative_to(workspace.root).as_posix() for p in workspace.protected_paths)
    runner = DockerExecutor(workspace.root, image, protected) if executor == "docker" else LocalExecutor(workspace.root)
    app = server("RepoPilot shell")

    @app.tool()
    def run_command(command: str, timeout: int = 60) -> str:
        """Execute a bounded command only when the server permits shell execution."""
        return execute(RunCommand(workspace, runner), {"command": command, "timeout": timeout},
                       allowed=allow_shell)

    return app


if __name__ == "__main__":
    run(create_server)
