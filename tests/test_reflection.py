"""Reflection is model advice, with identical bounded semantics in both runtimes."""
import json

import pytest

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.config import Settings
from repopilot.llm.base import FakeLLM


@pytest.fixture(params=["custom", "langgraph"])
def runtime(request):
    if request.param == "langgraph":
        pytest.importorskip("langgraph")
    return request.param


class RecordingLLM(FakeLLM):
    def __init__(self, responses):
        super().__init__(responses)
        self.prompts = []

    def chat(self, system, user):
        self.prompts.append(user)
        return super().chat(system, user)


def advice(success=False):
    return json.dumps({"success": success, "reason": "exception mapping", "next_action": "inspect schema",
                       "needs_search": True})


def test_failed_verification_reflects_replans_and_preserves_test(runtime_repo, runtime):
    script = demo_responses()
    weaker_plan = json.loads(script[0])
    weaker_plan["test_command"] = "true"
    model = RecordingLLM([script[0], script[-1], advice(True), json.dumps(weaker_plan),
                          script[3], advice(), script[-1]])
    agent = RepoPilot(runtime_repo, model, Settings(reflection_enabled=True),
                      executor="local", approval="auto", runtime=runtime)
    result = agent.run("fix duplicate email")
    assert result.status == "completed"
    assert result.plan.test_command == "python -m pytest -q"
    assert [h["ok"] for h in result.tool_history if h.get("phase") == "verification"] == [False, True]
    assert [r["phase"] for r in result.reflections] == ["verification_failed", "tool"]
    assert any("Reflection feedback:" in prompt and "inspect schema" in prompt for prompt in model.prompts)
    assert any("Reflection:" in prompt and "inspect schema" in prompt for prompt in model.prompts)
    if runtime == "langgraph":
        graph = agent.graph_runtime.graph.get_graph()
        edges = {(edge.source, edge.target) for edge in graph.edges}
        assert {("verify", "reflection"), ("reflection", "plan"), ("verify", "finalize")} <= edges


def test_invalid_reflection_uses_observations_without_false_success(runtime_repo, runtime):
    script = demo_responses()
    agent = RepoPilot(runtime_repo, FakeLLM([script[0], script[1], "invalid reflection"]),
                      Settings(reflection_enabled=True, max_steps=1),
                      executor="local", approval="auto", runtime=runtime)
    result = agent.run("fix")
    assert result.error == "max_steps" and not result.reflection.success
    assert result.reflection.reason == "Invalid reflection JSON"


def test_reflection_provider_error_persists_failure(runtime_repo, runtime):
    script = demo_responses()
    result = RepoPilot(runtime_repo, FakeLLM(script[:2]), Settings(reflection_enabled=True),
                       executor="local", approval="auto", runtime=runtime).run("fix")
    assert result.status == "failed" and result.current_step == 1
    assert len(result.tool_history) == 1
