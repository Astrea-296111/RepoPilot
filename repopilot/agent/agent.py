"""Straightforward model → tool → observation loop with bounded retries."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import time
from typing import Callable, Literal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from typing import Annotated, Union
from repopilot.config import Settings
from repopilot.context.repo_map import build_repo_map, render_repo_map
from repopilot.context.retrieval import retrieve_with_imports
from repopilot.context.manager import ContextManager
from repopilot.llm.base import LLM, LLMResponse
from repopilot.session.store import SessionStore
from repopilot.tools.base import ToolResult, Workspace
from repopilot.tools.filesystem import ReadFile, ApplyPatch, WriteFile
from repopilot.tools.search import SearchCode
from repopilot.tools.shell import LocalExecutor, RunCommand, bounded_output
from repopilot.tools.git import GitDiff
from repopilot.sandbox.docker import DockerExecutor
from .planner import plan_task
from .prompts import AGENT_SYSTEM
from .state import AgentState

log = logging.getLogger(__name__)


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["tool"]
    tool: Literal["read_file", "search_code", "apply_patch", "write_file", "run_command", "git_diff"]
    arguments: dict
    reason: str


class FinalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["final"]
    summary: str
    tests: str
    changed_files: list[str]


ACTION_ADAPTER = TypeAdapter(Annotated[Union[ToolAction, FinalAction], Field(discriminator="type")])


def parse_action(content: str) -> ToolAction | FinalAction:
    return ACTION_ADAPTER.validate_json(content)


def demo_responses() -> list[str]:
    """Known sequence for the deliberately broken example; no benchmark claim."""
    def call(tool: str, args: dict, reason: str) -> str:
        return json.dumps({"type": "tool", "tool": tool, "arguments": args, "reason": reason}, ensure_ascii=False)
    return [
        json.dumps({"goal": "修复重复邮箱错误", "suspected_files": ["app/users.py", "tests/test_users.py"],
                    "steps": ["读取代码", "复现失败", "修复并复测"], "test_command": "python -m pytest -q"}, ensure_ascii=False),
        call("read_file", {"path": "app/users.py"}, "确认异常传播"),
        call("run_command", {"command": "python -m pytest -q", "timeout": 60}, "复现错误"),
        call("apply_patch", {"path": "app/users.py", "old_text": "raise ValueError('UNIQUE constraint failed: users.email')",
                             "new_text": "raise DuplicateEmailError(email)"}, "修正异常映射"),
        call("run_command", {"command": "python -m pytest -q", "timeout": 60}, "验证修复"),
        call("git_diff", {}, "检查改动"),
        json.dumps({"type": "final", "summary": "重复邮箱现抛出 DuplicateEmailError", "tests": "python -m pytest -q 已通过",
                    "changed_files": ["app/users.py"]}, ensure_ascii=False),
    ]


class RepoPilot:
    def __init__(self, repo: Path, llm: LLM, settings: Settings, *, executor: str = "docker",
                 approval: str = "ask", approve: Callable[[str, dict], bool] | None = None,
                 protected_paths: tuple[str, ...] = ()):
        self.workspace = Workspace(repo, protected_paths)
        if executor not in {"docker", "local"} or approval not in {"ask", "auto", "never"}:
            raise ValueError("executor 或 approval 参数无效")
        self.executor_name, self.approval, self.approve = executor, approval, approve
        self.settings, self.llm = settings, llm
        shell = DockerExecutor(self.workspace.root, settings.docker_image, protected_paths) if executor == "docker" else LocalExecutor(self.workspace.root)
        self.tools = {tool.name: tool for tool in [ReadFile(self.workspace), SearchCode(self.workspace),
            ApplyPatch(self.workspace), WriteFile(self.workspace), RunCommand(self.workspace, shell), GitDiff(self.workspace)]}
        self.store = SessionStore(self.workspace.root)

    def _model(self, system: str, user: str, state: AgentState) -> LLMResponse:
        started = time.monotonic()
        response = self.llm.chat(system, user)
        state.token_usage["prompt_tokens"] += response.prompt_tokens
        state.token_usage["completion_tokens"] += response.completion_tokens
        state.token_usage["total_tokens"] += response.prompt_tokens + response.completion_tokens
        log.info("task=%s llm_latency=%.3fs", state.id, time.monotonic() - started)
        return response

    def _action(self, prompt: str, state: AgentState) -> ToolAction | FinalAction:
        for attempt in range(2):
            response = self._model(AGENT_SYSTEM, prompt, state)
            try:
                action = parse_action(response.content)
                state.messages.append({"role": "assistant", "content": response.content})
                return action
            except (ValidationError, ValueError) as exc:
                if attempt:
                    raise ValueError("Agent 连续两次输出无效 JSON；任务已暂停") from exc
                prompt += "\n上一条不符合协议，请只重新输出一个合法 JSON object。错误：" + str(exc)[:500]
        raise AssertionError("unreachable")

    def _permitted(self, tool: str, args: dict) -> bool:
        if tool not in {"apply_patch", "write_file", "run_command"}:
            return True
        if self.approval == "auto": return True
        if self.approval == "never": return False
        return bool(self.approve and self.approve(tool, args))

    def _execute(self, tool: str, args: dict, state: AgentState) -> ToolResult:
        started = time.monotonic()
        try:
            result = self.tools[tool].execute(args) if self._permitted(tool, args) else ToolResult(False, "Approval denied for " + tool)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result = ToolResult(False, f"{type(exc).__name__}: {exc}")
        result.output = bounded_output(result.output)
        log.info("task=%s step=%s tool=%s latency=%.3fs ok=%s", state.id, state.current_step,
                 tool, time.monotonic() - started, result.ok)
        if result.changed_file and result.changed_file not in state.changed_files:
            state.changed_files.append(result.changed_file)
        if tool == "run_command" and state.plan and args.get("command") == state.plan.test_command:
            state.test_status = "passed" if result.ok else "failed"
        state.tool_history.append({"step": state.current_step, "tool": tool, "arguments": args,
                                   "ok": result.ok, "exit_code": result.exit_code, "output": result.output,
                                   "latency_seconds": round(time.monotonic() - started, 3)})
        state.messages.append({"role": "tool", "content": f"{tool}: {result.output}"})
        return result

    def run(self, task: str, state: AgentState | None = None) -> AgentState:
        state = state or AgentState(task=task, repo_path=str(self.workspace.root),
                                   executor=self.executor_name, approval=self.approval)
        if Path(state.repo_path).resolve() != self.workspace.root or state.executor != self.executor_name or state.approval != self.approval:
            raise ValueError("恢复会话的仓库或运行选项与原会话不一致")
        if state.status == "completed": raise ValueError("已完成的会话无需恢复")
        state.status = "running"
        self.store.save(state)
        try:
            entries = build_repo_map(self.workspace.root)
            mapped = render_repo_map(entries)
            relevant = retrieve_with_imports(self.workspace.root, entries, state.task)
            state.retrieved_files = [path for path, _ in relevant]
            if state.plan is None:
                # Reuse the accounting adapter for the one planning call; planner handles repair.
                class Metered:
                    def __init__(inner, owner): inner.owner = owner
                    def chat(inner, system, user): return inner.owner._model(system, user, state)
                state.plan, _ = plan_task(Metered(self), state.task, mapped, relevant)
                self.store.save(state)
            while state.current_step < self.settings.max_steps:
                prompt = ContextManager(self.settings.max_context_chars).build(state, mapped, relevant)
                action = self._action(prompt, state)
                state.current_step += 1
                if isinstance(action, FinalAction):
                    # Do not trust a model's tests field: run the planned test now.
                    command = state.plan.test_command
                    result = self._execute("run_command", {"command": command, "timeout": 60}, state)
                    if result.ok:
                        diff = self._execute("git_diff", {}, state)
                        state.final_diff = diff.output
                        if not diff.ok:
                            state.finish("failed", "无法生成 Git Diff；请先在目标仓库初始化 Git")
                            state.error = "git_diff_failed"
                            self.store.save(state)
                            return state
                        state.finish("completed", action.summary)
                        self.store.save(state)
                        return state
                    state.messages.append({"role": "system", "content": "Final verification failed. Fix the observed error before final."})
                else:
                    fingerprint = json.dumps([action.tool, action.arguments], sort_keys=True, ensure_ascii=False)
                    recent = [item.get("fingerprint") for item in state.tool_history[-2:]]
                    if recent == [fingerprint, fingerprint]:
                        state.finish("failed", "检测到连续 3 次相同工具调用，已停止")
                        state.error = "loop_detection"
                        break
                    result = self._execute(action.tool, action.arguments, state)
                    state.tool_history[-1]["fingerprint"] = fingerprint
                    if recent and recent[-1] == fingerprint:
                        state.messages.append({"role": "system", "content": "连续重复同一工具调用；请改变方法或完成任务。"})
                self.store.save(state)
            else:
                state.finish("failed", "达到 max_steps，任务未完成")
                state.error = "max_steps"
        except Exception as exc:
            state.finish("failed", "执行中断")
            state.error = str(exc)
            log.exception("task=%s error=%s", state.id, exc)
        self.store.save(state)
        return state
