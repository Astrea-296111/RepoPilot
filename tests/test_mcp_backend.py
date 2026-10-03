"""Exercise the actual Agent → MCP SDK client → stdio server → Python tool path."""
import asyncio
import json

import pytest

pytest.importorskip("mcp")
from mcp import Client

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.mcp_server.filesystem_server import create_server
from repopilot.tools.backends import MCPToolBackend
from repopilot.tools.base import Workspace


@pytest.mark.parametrize("runtime", ["custom", "langgraph"])
def test_agent_repairs_using_real_mcp_backend(runtime_repo, runtime):
    if runtime == "langgraph":
        pytest.importorskip("langgraph")
    agent = RepoPilot(runtime_repo, FakeLLM(demo_responses()), Settings(),
                      executor="local", approval="auto", runtime=runtime, tool_backend="mcp")
    result = agent.run("fix duplicate email")
    assert result.status == "completed", result.error or result.tool_history
    assert result.test_status == "passed" and result.changed_files == ["app/users.py"]
    assert agent.backend._stack is None and not agent.backend._clients


def test_server_write_opt_in_is_independent_of_client(runtime_repo):
    async def exercise():
        async with Client(create_server(Workspace(runtime_repo))) as client:
            denied = await client.call_tool("write_file", {"path": "forbidden.py", "content": "x"})
            assert denied.is_error
        assert not (runtime_repo / "forbidden.py").exists()
    asyncio.run(exercise())


def test_mcp_boundary_protected_paths_status_and_shell_errors(runtime_repo):
    backend = MCPToolBackend(runtime_repo, executor="local", image="unused", allow_mutation=True,
                             protected_paths=("tests",))
    try:
        denied = backend.execute("apply_patch", {"path": "tests/test_users.py", "old_text": "DuplicateEmailError",
                                                "new_text": "ValueError"})
        assert not denied.ok and "受保护" in denied.output
        assert not backend.execute("read_file", {"path": "../private.txt"}).ok
        created = backend.execute("write_file", {"path": "new.py", "content": "x=1\n"})
        assert created.ok and created.changed_file == "new.py"
        status = backend.execute("git_status", {})
        assert status.ok and "new.py" in status.output
        error = backend.execute("run_command", {"command": "exit 7"})
        assert not error.ok and error.exit_code == 7
    finally:
        backend.close()


def test_approval_never_stops_mutation_before_protocol_call(runtime_repo, monkeypatch):
    script = demo_responses()
    agent = RepoPilot(runtime_repo, FakeLLM([script[0], script[3]]), Settings(max_steps=1),
                      executor="local", approval="never", tool_backend="mcp")
    monkeypatch.setattr(agent.backend, "execute", lambda *args: pytest.fail("Approval must run first"))
    result = agent.run("fix")
    assert result.error == "max_steps"
    assert not result.tool_history[0]["executed"]
