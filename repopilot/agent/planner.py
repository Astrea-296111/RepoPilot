"""One model call for a compact, validated plan with one repair attempt."""
from pydantic import ValidationError
from repopilot.llm.base import LLM
from .state import Plan
from .prompts import PLANNER_SYSTEM


def _normalize_test_command(command: str) -> str:
    """Prefer module execution for pytest so cwd import behavior is consistent across platforms."""
    stripped = command.strip()
    if stripped == "pytest" or stripped.startswith("pytest "):
        return "python -m " + stripped
    return stripped


def plan_task(llm: LLM, task: str, repo_map: str, relevant: list[tuple[str, int]]) -> tuple[Plan, list[int]]:
    context = f"Task: {task}\nRepo map:\n{repo_map[:12000]}\nTop files: {relevant}"
    usage = [0, 0]
    for attempt in range(2):
        response = llm.chat(PLANNER_SYSTEM, context)
        usage[0] += response.prompt_tokens
        usage[1] += response.completion_tokens
        try:
            plan = Plan.model_validate_json(response.content)
            plan.test_command = _normalize_test_command(plan.test_command)
            return plan, usage
        except ValidationError as exc:
            if attempt:
                raise ValueError("Planner 连续两次输出无效 JSON；请换模型或重试") from exc
            context += "\n上次输出不符合 JSON schema。请严格按字段重写：" + str(exc)[:600]
    raise AssertionError("unreachable")
