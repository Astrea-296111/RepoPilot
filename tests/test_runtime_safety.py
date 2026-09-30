"""Pre-refactor regression protection, including observed termination failure."""
import importlib
import json
from pathlib import Path

import pytest

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.agent.state import AgentState
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM
from repopilot.sandbox.docker import DockerExecutor
from repopilot.tools.shell import LocalExecutor


@pytest.mark.parametrize("executor,kind", [("local", LocalExecutor), ("docker", DockerExecutor)])
def test_executor_selection(runtime_repo, executor, kind):
    pilot = RepoPilot(runtime_repo, FakeLLM([]), Settings(), executor=executor)
    assert isinstance(pilot.tools["run_command"].executor, kind)


def test_interactive_approval_is_applied_to_mutation(runtime_repo):
    requested = []
    pilot = RepoPilot(runtime_repo, FakeLLM([]), Settings(), executor="local",
                      approve=lambda tool, args: requested.append(tool) or False)
    state = AgentState(task="fix", repo_path=str(runtime_repo))
    patch = json.loads(demo_responses()[3])["arguments"]
    assert not pilot._execute("apply_patch", patch, state).ok
    assert requested == ["apply_patch"]
    assert "raise ValueError" in (runtime_repo / "app/users.py").read_text()


def test_valid_json_after_one_repair(runtime_repo):
    script = demo_responses()
    state = RepoPilot(runtime_repo, FakeLLM([script[0], "invalid", script[1]]),
                      Settings(max_steps=1), executor="local", approval="auto").run("fix")
    assert state.error == "max_steps"
    assert len(state.tool_history) == 1 and state.tool_history[0]["tool"] == "read_file"


def test_failed_final_verification_returns_to_agent(runtime_repo):
    script = demo_responses()
    state = RepoPilot(runtime_repo, FakeLLM([script[0], script[-1], script[3], script[-1]]),
                      Settings(), executor="local", approval="auto").run("fix")
    assert state.status == "completed"
    tests = [h for h in state.tool_history if h["tool"] == "run_command"]
    assert [h["ok"] for h in tests] == [False, True]
    assert any("Final verification failed" in m["content"] for m in state.messages)


def test_successful_test_repeat_finishes_with_independent_verification(runtime_repo):
    script = demo_responses()
    state = RepoPilot(runtime_repo, FakeLLM([script[0], script[3], *([script[4]] * 3)]),
                      Settings(), executor="local", approval="auto").run("fix")
    # Same sequence reproduced loop_detection in the baseline commit.
    assert state.status == "completed" and state.error == ""
    assert state.test_status == "passed"
    commands = [h for h in state.tool_history if h["tool"] == "run_command"]
    assert len(commands) == 2 and commands[-1]["phase"] == "verification"
    assert all(h["executed"] for h in commands)


def test_external_hidden_suite_is_injected_only_into_grader(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "eval"))
    runner = importlib.import_module("run_external")
    task = json.loads((root / "eval/external/tasks.json").read_text())[0]
    observed = []

    def execute(repo, command, settings, local=False):
        observed.append((repo / "tests/test_hidden.py").exists())
        return {"exit_code": 0 if observed[-1] else 1,
                "output": "1 passed" if observed[-1] else "FAILED public reproducer"}

    monkeypatch.setattr(runner, "execute", execute)
    source = next(p for p in (root / task["repo"] / task["allowed_source_dir"]).glob("*.py")
                  if p.stat().st_size)
    original = source.read_text()
    response = {"summary": "isolation test", "patches": [{
        "path": source.relative_to(root / task["repo"]).as_posix(),
        "old_text": original, "new_text": original + "\n# isolation probe\n"}]}
    monkeypatch.setattr(runner, "OpenAICompatibleLLM", lambda settings: FakeLLM([json.dumps(response)]))
    record = runner.trial(task, 1, "oneshot", Settings())
    assert record["resolved"], record
    assert observed == [False, True]
