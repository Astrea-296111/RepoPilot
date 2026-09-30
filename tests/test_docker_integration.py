"""Opt-in real Docker execution; CI builds the sandbox before enabling this file."""
import os
from pathlib import Path
import shutil

import pytest

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.sandbox.docker import DockerExecutor

pytestmark = pytest.mark.skipif(os.getenv("REPOPILOT_DOCKER_TESTS") != "1" or not shutil.which("docker"),
                                reason="Requires built sandbox image and REPOPILOT_DOCKER_TESTS=1")


def image():
    return os.getenv("REPOPILOT_DOCKER_IMAGE", "repopilot-sandbox:dev")


@pytest.mark.parametrize("runtime", ["custom", "langgraph"])
def test_real_docker_trusted_demo(runtime_repo, runtime):
    if runtime == "langgraph":
        pytest.importorskip("langgraph")
    state = RepoPilot(runtime_repo, FakeLLM(demo_responses()), Settings(docker_image=image()),
                      runtime=runtime, executor="docker", approval="auto", protected_paths=("tests",)).run("fix")
    assert state.status == "completed" and state.test_status == "passed"
    assert any(h.get("phase") == "verification" and h["ok"] for h in state.tool_history)


def test_real_docker_resource_network_and_environment_restrictions(runtime_repo, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "HOST_SECRET_MUST_STAY_OUTSIDE")
    script = '''
import os
from pathlib import Path
assert os.environ.get("LLM_API_KEY") is None
assert Path("/sys/fs/cgroup/memory.max").read_text().strip() == "536870912"
assert Path("/sys/fs/cgroup/pids.max").read_text().strip() == "128"
assert Path("/sys/fs/cgroup/cpu.max").read_text().split()[0] == "100000"
routes = Path("/proc/net/route").read_text().splitlines()[1:]
assert not any(line.split()[1] == "00000000" for line in routes)
status = Path("/proc/self/status").read_text()
assert "NoNewPrivs:\\t1" in status
try:
    Path("/etc/repopilot-should-not-write").write_text("blocked")
except OSError:
    pass
else:
    raise AssertionError("container root filesystem is writable")
Path("/tmp/repopilot-allowed").write_text("ok")
print("resource, network, filesystem and environment restrictions passed")
'''
    result = DockerExecutor(runtime_repo, image()).run("python - <<'PY'\n" + script + "\nPY", 15)
    assert result.ok, result.output


def test_real_docker_protected_tests_are_read_only(runtime_repo):
    target = runtime_repo / "tests/test_users.py"
    before = target.read_text()
    result = DockerExecutor(runtime_repo, image(), ("tests",)).run("echo tampered > tests/test_users.py", 10)
    assert not result.ok and target.read_text() == before


def test_real_docker_timeout_removes_container(runtime_repo):
    result = DockerExecutor(runtime_repo, image()).run("python -c 'import time; time.sleep(30)'", 1)
    assert result.exit_code == 124 and "timed out" in result.output
