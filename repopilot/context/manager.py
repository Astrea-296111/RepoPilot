"""A bounded prompt made from task, plan, map, relevant code and history."""
from __future__ import annotations
from pathlib import Path
import json
from repopilot.agent.state import AgentState
from repopilot.tools.shell import bounded_output
from .excerpts import source_excerpt


class ContextManager:
    def __init__(self, budget: int = 30000):
        if budget < 2000: raise ValueError("Context budget must be at least 2000 characters")
        self.budget = budget

    def build(self, state: AgentState, repo_map: str, relevant: list[tuple[str, int]]) -> str:
        # Runtime feedback must reach the next model prompt; storing a system message alone is insufficient.
        feedback = json.dumps(state.recovery, ensure_ascii=False)[:1000] if state.recovery else "none"
        required = (f"Runtime feedback: {feedback}\nTask: {state.task[:self.budget // 4]}\n"
                    f"Reflection: {state.reflection.model_dump_json()[:1500] if state.reflection else 'none'}\n"
                    f"Step: {state.current_step}\nTest status: {state.test_status}\n"
                    f"Planned test: {state.plan.test_command if state.plan else 'none'}\n"
                    f"Changed: {state.changed_files}\nPlan: {state.plan.model_dump_json() if state.plan else 'none'}")
        # Keep recent observations in detail; summarize older actions as a short memory.
        older = state.tool_history[:-4]
        memory = "\n".join(f"- {item['tool']} {str(item['arguments'])[:90]}: {'ok' if item['ok'] else 'failed'}" for item in older[-15:])
        recent = "\n".join(f"{item['tool']} {str(item['arguments'])[:300]} -> {bounded_output(item['output'], 1800)}" for item in state.tool_history[-4:])
        relevant_code = []
        root = Path(state.repo_path)
        for relative, _score in relevant[:3]:
            path = (root / relative).resolve()
            if path.is_relative_to(root.resolve()) and path.is_file():
                source = path.read_text(encoding='utf-8', errors='replace')
                hit = next((hit for hit in state.retrieval_results if hit["path"] == relative), None)
                if hit:
                    lines = source.splitlines()
                    excerpt = "\n".join(lines[max(0, hit["start_line"] - 1):hit["end_line"]])[:2400]
                    excerpt = f"score={hit['score']} reason={hit['reason']} lines={hit['start_line']}-{hit['end_line']}\n" + excerpt
                else:
                    excerpt = source_excerpt(source, state.task) if len(source) > 7000 else source[:1400]
                relevant_code.append(f"{relative}:\n{excerpt}")
        # Priority: required > newest observations > memory > relevant code > repo map.
        experiences = json.dumps(state.memory_hits, ensure_ascii=False)[:2500] if state.memory_hits else "none"
        sections = [("\nRecent observations:\n", recent),
                    ("\nHistorical repairs (reference only; verify current code):\n", experiences),
                    ("\nEarlier memory:\n", memory),
                    ("\nRelevant code:\n", "\n".join(relevant_code)), ("\nRepo map:\n", repo_map)]
        result = required[: self.budget // 2]
        for label, content in sections:
            remaining = self.budget - len(result) - len(label)
            if remaining > 0:
                result += label + content[:remaining]
        return result[: self.budget]
