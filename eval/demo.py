"""Key-free CLI demonstration in a temporary, trusted copy of the broken demo."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> int:
    """Exercise the installed CLI without changing the checked-in bug fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("custom", "langgraph"), default="custom")
    parser.add_argument("--executor", choices=("local", "docker"), default="local")
    parser.add_argument("--trace", action="store_true", help="Export metadata-only console spans to stderr")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
           "REPOPILOT_OTEL_ENABLED": "1" if args.trace else "0",
           "REPOPILOT_OTEL_EXPORTER": "console", "OTEL_TRACES_SAMPLER": "always_on"}
    with tempfile.TemporaryDirectory(prefix="repopilot-demo-") as directory:
        repo = Path(directory) / "repo"
        shutil.copytree(root / "examples/demo_repo", repo,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git", ".repopilot"))
        for command in (["git", "init", "-q"], ["git", "add", "."],
                        ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.invalid",
                         "commit", "-qm", "broken baseline"]):
            subprocess.run(command, cwd=repo, check=True, timeout=15)
        result = subprocess.run(
            [sys.executable, "-m", "repopilot.cli", "run", str(repo), "fix duplicate email",
             "--fake-demo", "--runtime", args.runtime, "--executor", args.executor, "--approval", "auto"],
            cwd=root, env=env, timeout=120)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
