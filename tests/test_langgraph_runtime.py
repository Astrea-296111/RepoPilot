"""Exercise real graph transitions, feedback, safety and both persistence paths."""
import json
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("langgraph")

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.agent.state import AgentState
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.session.store import SessionStore


def pilot(repo, script, max_steps=15, **kwargs):
    return RepoPilot(repo, FakeLLM(script), Settings(max_steps=max_steps), runtime="langgraph",
                     executor="local", approval="auto", **kwargs)


def test_graph_success_and_custom_semantics(runtime_repo, monkeypatch):
    other = runtime_repo.parent / "custom"
    shutil.copytree(runtime_repo, other)
    custom = RepoPilot(other, FakeLLM(demo_responses()), Settings(), executor="local", approval="auto").run("fix")
    graph = pilot(runtime_repo, demo_responses())
    monkeypatch.setattr(graph, "_run_custom", lambda state: pytest.fail("Legacy loop must not run inside graph"))
    result = graph.run("fix")
    assert result.status == custom.status == "completed"
    assert result.current_step == custom.current_step == 6
    assert result.final_diff == custom.final_diff
    assert result.token_usage == custom.token_usage
    assert [(h["tool"], h["ok"]) for h in result.tool_history] == [(h["tool"], h["ok"]) for h in custom.tool_history]
    assert {"prepare_repo_context", "plan", "agent_decide", "tool_execute", "verify", "finalize"}.issubset(
        graph.graph_runtime.graph.get_graph().nodes)


def test_graph_tool_failure_then_recovery(runtime_repo):
    s = demo_responses()
    missing = json.dumps({"type": "tool", "tool": "read_file", "reason": "inspect",
                          "arguments": {"path": "missing.py"}})
    state = pilot(runtime_repo, [s[0], missing, s[3], s[-1]]).run("fix")
    assert state.status == "completed" and not state.tool_history[0]["ok"]


def test_graph_final_verification_failure_returns_to_decision(runtime_repo):
    s = demo_responses()
    state = pilot(runtime_repo, [s[0], s[-1], s[3], s[-1]]).run("fix")
    assert state.status == "completed"
    assert [h["ok"] for h in state.tool_history if h.get("phase") == "verification"] == [False, True]


def test_graph_max_steps(runtime_repo):
    state = pilot(runtime_repo, demo_responses()[:2], max_steps=1).run("fix")
    assert state.error == "max_steps" and state.current_step == 1


def test_graph_repeat_guard(runtime_repo):
    s = demo_responses()
    state = pilot(runtime_repo, [s[0], s[1], s[1], s[1], s[1]]).run("fix")
    assert state.error == "loop_detection" and state.current_step == 4


def test_graph_session_bridge_across_instances(runtime_repo):
    s = demo_responses()
    first = pilot(runtime_repo, s[:2]).run("fix")
    saved = SessionStore(runtime_repo).load(first.id)
    assert saved.runtime == "langgraph" and saved.current_step == 1
    second = pilot(runtime_repo, s[2:]).run(saved.task, saved)
    assert second.status == "completed" and second.current_step == 6
    assert sum(h["tool"] == "read_file" for h in second.tool_history) == 1
    with pytest.raises(ValueError, match="原会话"):
        RepoPilot(runtime_repo, FakeLLM([]), Settings(), executor="local", approval="auto").run("fix", first)


def test_graph_in_memory_checkpoint_resumes_after_tool_without_replay(runtime_repo):
    graph = pilot(runtime_repo, demo_responses()).graph_runtime
    state = AgentState(task="fix", repo_path=str(runtime_repo), runtime="langgraph",
                       executor="local", approval="auto", status="running")
    config = graph.config(state)
    paused = graph.graph.invoke(graph.input(state), config, interrupt_after=["tool_execute"])
    assert paused["agent"]["current_step"] == 1
    assert graph.graph.get_state(config).next == ("agent_decide",)
    resumed = graph.graph.invoke(None, config)
    assert resumed["agent"]["status"] == "completed"
    assert sum(h["tool"] == "read_file" for h in resumed["agent"]["tool_history"]) == 1


def test_graph_uses_shared_protected_path_policy(runtime_repo):
    s = demo_responses()
    patch = json.dumps({"type": "tool", "tool": "apply_patch", "reason": "forbidden",
                        "arguments": {"path": "tests/test_users.py", "old_text": "DuplicateEmailError",
                                      "new_text": "ValueError"}})
    state = pilot(runtime_repo, [s[0], patch], max_steps=1, protected_paths=("tests",)).run("fix")
    assert not state.tool_history[0]["ok"] and "受保护" in state.tool_history[0]["output"]


def test_graph_cli_smoke(runtime_repo):
    result = subprocess.run([sys.executable, "-m", "repopilot.cli", "run", str(runtime_repo),
                             "fix duplicate email", "--runtime", "langgraph", "--fake-demo",
                             "--executor", "local", "--approval", "auto"],
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Status: completed" in result.stdout and "Tests: passed" in result.stdout


def test_graph_api_selector(runtime_repo, monkeypatch):
    from fastapi.testclient import TestClient
    from repopilot.api import server
    monkeypatch.setenv("REPOPILOT_API_ROOT", str(runtime_repo.parent))
    monkeypatch.setenv("REPOPILOT_API_ALLOW_LOCAL", "1")
    monkeypatch.setattr(server, "OpenAICompatibleLLM", lambda settings: FakeLLM(demo_responses()))
    with TestClient(server.app) as client:
        response = client.post("/api/tasks", json={"repo_path": str(runtime_repo), "task": "fix",
                                                  "executor": "local", "approval": "auto", "runtime": "langgraph"})
        assert response.status_code == 202, response.text
        saved = client.get("/api/tasks/" + response.json()["id"]).json()
    assert saved["status"] == "completed" and saved["runtime"] == "langgraph"
