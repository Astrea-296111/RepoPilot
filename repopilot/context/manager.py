"""A bounded prompt made from task, plan, map, relevant code and history."""
from __future__ import annotations
from pathlib import Path
from repopilot.agent.state import AgentState
from repopilot.tools.shell import bounded_output


class ContextManager:
    def __init__(self, budget: int = 30000):
        if budget < 2000: raise ValueError("Context budget must be at least 2000 characters")
        self.budget = budget

    def build(self, state: AgentState, repo_map: str, relevant: list[tuple[str, int]]) -> str:
        required = f"Task: {state.task}\nStep: {state.current_step}\nTest status: {state.test_status}\nChanged: {state.changed_files}\nPlan: {state.plan.model_dump_json() if state.plan else 'none'}"
        # Keep recent observations in detail; summarize older actions as a short memory.
        older = state.tool_history[:-4]
        memory = "\n".join(f"- {item['tool']} {str(item['arguments'])[:90]}: {'ok' if item['ok'] else 'failed'}" for item in older[-15:])
        recent = "\n".join(f"{item['tool']} {str(item['arguments'])[:300]} -> {bounded_output(item['output'], 1800)}" for item in state.tool_history[-4:])
        relevant_code = []
        root = Path(state.repo_path)
        for relative, _score in relevant[:3]:
            path = (root / relative).resolve()
            if path.is_relative_to(root.resolve()) and path.is_file():
                relevant_code.append(f"{relative}:\n{path.read_text(encoding='utf-8', errors='replace')[:1400]}")
        # Priority: required > newest observations > memory > relevant code > repo map.
        sections = [("\nRecent observations:\n", recent), ("\nEarlier memory:\n", memory),
                    ("\nRelevant code:\n", "\n".join(relevant_code)), ("\nRepo map:\n", repo_map)]
        result = required[: self.budget // 2]
        for label, content in sections:
            remaining = self.budget - len(result) - len(label)
            if remaining > 0:
                result += label + content[:remaining]
        return result[: self.budget]
