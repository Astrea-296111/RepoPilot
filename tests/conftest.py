"""Isolated Git checkout shared by runtime and protocol integration tests."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture
def runtime_repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/demo_repo", root)
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=10)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, timeout=10)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-qm", "baseline"],
                   check=True, timeout=10)
    return root
