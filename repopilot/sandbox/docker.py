"""Run one command in a constrained, temporary Docker container."""
from __future__ import annotations
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from repopilot.tools.base import ToolResult
from repopilot.tools.shell import bounded_output


class DockerExecutor:
    def __init__(self, root: Path, image: str = "repopilot-sandbox:dev"):
        self.root = root.resolve()
        self.image = image

    def run(self, command: str, timeout: int) -> ToolResult:
        if not shutil.which("docker"):
            return ToolResult(False, "Docker executable not found. Install/start Docker or choose --executor local for trusted code.", 127)
        # No host secrets are passed. The target checkout is writable; network is disabled.
        with tempfile.TemporaryDirectory() as temp:
            cid = Path(temp) / "container.id"
            args = ["docker", "run", "--rm", "--cidfile", str(cid), "--network", "none",
                    "--read-only", "--tmpfs", "/tmp:rw,size=64m", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges", "--pids-limit", "128",
                    "--memory", "512m", "--cpus", "1", "--user", f"{getattr(os, 'getuid', lambda: 10001)()}:{getattr(os, 'getgid', lambda: 10001)()}",
                    "-e", "HOME=/tmp", "--mount", f"type=bind,source={self.root},target=/workspace",
                    "--workdir", "/workspace", self.image, "sh", "-lc", command]
            try:
                proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 10)
                output = bounded_output(proc.stdout + ("\nstderr:\n" + proc.stderr if proc.stderr else ""))
                return ToolResult(proc.returncode == 0, output, proc.returncode)
            except subprocess.TimeoutExpired:
                if cid.exists():
                    subprocess.run(["docker", "rm", "-f", cid.read_text().strip()], capture_output=True, timeout=10)
                return ToolResult(False, f"Docker command timed out after {timeout + 10}s", 124)
