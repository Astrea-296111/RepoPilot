"""Timed command executors and the run_command tool."""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
from typing import Protocol
from .base import ToolResult, Workspace

MAX_OUTPUT = 12000


def bounded_output(content: str, budget: int = MAX_OUTPUT) -> str:
    if len(content) <= budget:
        return content
    lines = content.splitlines()
    failures = [line[:300] for line in lines if any(word in line.lower() for word in ("error", "failed", "traceback", "exception"))]
    middle = "\n".join(failures[:12])[: budget // 3]
    head = content[: budget // 3]
    tail = content[-(budget - len(head) - len(middle) - 80):]
    return head + "\n[output truncated; relevant errors]\n" + middle + "\n[tail]\n" + tail


class CommandExecutor(Protocol):
    def run(self, command: str, timeout: int) -> ToolResult: ...


class LocalExecutor:
    """Explicitly opted-in local shell; use only with trusted repositories."""
    def __init__(self, root: Path): self.root = root.resolve()

    def run(self, command: str, timeout: int) -> ToolResult:
        allowed_env = {key: value for key, value in os.environ.items() if key in {
            "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "VIRTUAL_ENV",
            "PYTHONPATH", "SYSTEMROOT", "COMSPEC", "PATHEXT"}}
        process = subprocess.Popen(command, shell=True, cwd=self.root, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, env={**allowed_env, "PYTHONUNBUFFERED": "1"})
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            output = stdout + ("\nstderr:\n" + stderr if stderr else "")
            return ToolResult(process.returncode == 0, bounded_output(output), process.returncode)
        except subprocess.TimeoutExpired:
            if os.name == "posix": os.killpg(process.pid, signal.SIGKILL)
            else: process.kill()
            stdout, _ = process.communicate()
            return ToolResult(False, bounded_output(f"Command timed out after {timeout}s\n{stdout}"), 124)


class RunCommand:
    name = "run_command"
    description = "Run a shell command in the selected executor with timeout"

    def __init__(self, workspace: Workspace, executor: CommandExecutor):
        self.workspace, self.executor = workspace, executor

    def execute(self, args: dict) -> ToolResult:
        command = args["command"]
        timeout = int(args.get("timeout", 60))
        if not isinstance(command, str) or not command.strip() or len(command) > 2000 or not 1 <= timeout <= 120:
            raise ValueError("命令不能为空、不能过长，timeout 必须为 1–120 秒")
        return self.executor.run(command, timeout)
