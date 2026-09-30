"""Deterministic failure trajectories exercise policy, not model persuasion alone."""
import json

import pytest

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.agent.state import AgentState, Plan
from repopilot.config import Settings
from repopilot.context.manager import ContextManager
from repopilot.llm.base import FakeLLM
from repopilot.tools.base import ToolResult


@pytest.fixture(params=["custom", "langgraph"])
def runtime(request):
    if request.param == "langgraph":
        pytest.importorskip("langgraph")
    return request.param


class ObservedLLM(FakeLLM):
    def __init__(self, script):
        super().__init__(script)
        self.prompts = []

    def chat(self, system, user):
        self.prompts.append(user)
        return super().chat(system, user)


def make_pilot(repo, script, runtime, **kwargs):
    return RepoPilot(repo, script, Settings(), executor="local", approval="auto", runtime=runtime, **kwargs)


def test_repeated_read_reuses_evidence_and_feedback_reaches_next_model(runtime_repo, runtime, monkeypatch):
    s = demo_responses()
    llm = ObservedLLM([s[0], s[1], s[1], s[1], s[3], s[-1]])
    pilot = make_pilot(runtime_repo, llm, runtime)
    actual = pilot.tools["read_file"].execute
    executions = []
    monkeypatch.setattr(pilot.tools["read_file"], "execute", lambda args: executions.append(args) or actual(args))
    state = pilot.run("fix")
    assert state.status == "completed" and len(executions) == 1
    reads = [h for h in state.tool_history if h["tool"] == "read_file"]
    assert [h["cached"] for h in reads] == [False, True, True]
    assert '"count": 2' in llm.prompts[3] and '"count": 3' in llm.prompts[4]
    assert "Search dependencies/call sites" in llm.prompts[4]


def test_recovery_has_a_hard_stop(runtime_repo, runtime):
    s = demo_responses()
    state = make_pilot(runtime_repo, FakeLLM([s[0], *([s[1]] * 4)]), runtime).run("fix")
    assert state.error == "loop_detection" and state.current_step == 4
    assert sum(h.get("executed", True) for h in state.tool_history) == 1


def test_repeated_passing_planned_tests_execute_final_suite(runtime_repo, runtime, monkeypatch):
    s = demo_responses()
    pilot = make_pilot(runtime_repo, FakeLLM([s[0], s[3], s[4], s[4], s[4]]), runtime)
    actual = pilot.tools["run_command"].execute
    executions = []
    monkeypatch.setattr(pilot.tools["run_command"], "execute", lambda args: executions.append(args) or actual(args))
    state = pilot.run("fix")
    assert state.status == "completed" and len(executions) == 2
    assert state.current_step == 3
    assert state.tool_history[-2]["phase"] == "verification"
    assert not any(h.get("cached") for h in state.tool_history if h["tool"] == "run_command")


def test_final_suite_failure_after_passing_observation_returns_to_agent(runtime_repo, runtime):
    s = demo_responses()
    llm = ObservedLLM([s[0], s[3], s[4], s[4], s[-1]])
    pilot = make_pilot(runtime_repo, llm, runtime)

    class SequencedExecutor:
        def __init__(self):
            self.calls = 0
        def run(self, command, timeout):
            self.calls += 1
            return ToolResult(self.calls != 2, "FAILED independent check" if self.calls == 2 else "1 passed",
                              1 if self.calls == 2 else 0)

    executor = SequencedExecutor()
    pilot.tools["run_command"].executor = executor
    state = pilot.run("fix")
    assert state.status == "completed" and executor.calls == 3
    assert "verification_failed" in llm.prompts[-1]
    assert [h["ok"] for h in state.tool_history if h.get("phase") == "verification"] == [False, True]


def test_mutation_invalidates_passing_test_evidence(runtime_repo, runtime):
    s = demo_responses()
    broken_again = json.loads(s[3])
    broken_again["arguments"]["old_text"], broken_again["arguments"]["new_text"] = (
        broken_again["arguments"]["new_text"], broken_again["arguments"]["old_text"])
    script = [s[0], s[3], s[4], json.dumps(broken_again), s[4], s[3], s[-1]]
    state = make_pilot(runtime_repo, FakeLLM(script), runtime).run("fix")
    assert state.status == "completed"
    assert [h["ok"] for h in state.tool_history if h["tool"] == "run_command"] == [True, False, True]
    assert state.workspace_revision == 3


def test_arbitrary_command_invalidates_test_evidence(runtime_repo, runtime):
    pilot = make_pilot(runtime_repo, FakeLLM([]), runtime)
    state = AgentState(task="fix", repo_path=str(runtime_repo), plan=Plan(goal="fix", test_command="python -m pytest -q"),
                       test_status="passed", test_revision=0)
    pilot._execute("run_command", {"command": "echo changed", "timeout": 5}, state)
    assert state.test_status == "not_run" and state.test_revision is None and state.workspace_revision == 1


def test_feedback_retained_under_small_context_budget(runtime_repo):
    state = AgentState(task="fix", repo_path=str(runtime_repo), plan=Plan(goal="fix"),
                       recovery={"event": "repeated_action", "count": 3, "next": "Change strategy"})
    prompt = ContextManager(2000).build(state, "map" * 10000, [])
    assert len(prompt) <= 2000 and "repeated_action" in prompt and "Change strategy" in prompt
