"""Straightforward model → tool → observation loop with bounded retries."""
from __future__ import annotations
import json
import logging
from dataclasses import asdict
from pathlib import Path
import time
from uuid import uuid4
from typing import Callable, Literal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from typing import Annotated, Union
from repopilot.config import Settings
from repopilot.context.repo_map import build_repo_map, render_repo_map
from repopilot.context.retrieval import retrieve_with_imports
from repopilot.context.manager import ContextManager
from repopilot.llm.base import LLM, LLMResponse
from repopilot.observability import Tracing
from repopilot.session.store import SessionStore
from repopilot.tools.base import ToolResult, Workspace
from repopilot.tools.filesystem import ReadFile, ApplyPatch, WriteFile
from repopilot.tools.search import SearchCode
from repopilot.tools.shell import LocalExecutor, RunCommand, bounded_output
from repopilot.tools.git import GitDiff, GitStatus
from repopilot.tools.backends import MCPToolBackend, PythonToolBackend, ToolBackend
from repopilot.sandbox.docker import DockerExecutor
from .planner import plan_task
from .prompts import AGENT_SYSTEM
from .state import AgentState, Reflection
from .reflection import REFLECTION_SYSTEM, reflection_prompt

log = logging.getLogger(__name__)


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["tool"]
    tool: Literal["read_file", "search_code", "apply_patch", "write_file", "run_command", "git_diff", "git_status"]
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
                 protected_paths: tuple[str, ...] = (), runtime: str = "custom", tracing: Tracing | None = None,
                 tool_backend: str = "python", store: SessionStore | None = None):
        self.workspace = Workspace(repo, protected_paths)
        if executor not in {"docker", "local"} or approval not in {"ask", "auto", "never"}:
            raise ValueError("executor 或 approval 参数无效")
        self.executor_name, self.approval, self.approve = executor, approval, approve
        self.settings, self.llm = settings, llm
        self.tracing = tracing if tracing is not None else Tracing.from_settings(settings)
        if runtime not in {"custom", "langgraph"}:
            raise ValueError("runtime must be custom or langgraph")
        self.runtime = runtime
        self._invocation_id = uuid4().hex
        shell = DockerExecutor(self.workspace.root, settings.docker_image, protected_paths) if executor == "docker" else LocalExecutor(self.workspace.root)
        self.tools = {tool.name: tool for tool in [ReadFile(self.workspace), SearchCode(self.workspace),
            ApplyPatch(self.workspace), WriteFile(self.workspace), RunCommand(self.workspace, shell), GitDiff(self.workspace), GitStatus(self.workspace)]}
        if tool_backend not in {"python", "mcp"}:
            raise ValueError("tool_backend must be python or mcp")
        self.tool_backend_name = tool_backend
        self._context_cache = None
        self._context_revision = -1
        self.embedder = None
        if settings.retrieval_mode == "hybrid" and settings.embedding_model:
            from repopilot.context.embeddings import OpenAIEmbeddings
            self.embedder = OpenAIEmbeddings(settings.embedding_base_url, settings.embedding_api_key, settings.embedding_model)
        self.backend: ToolBackend = (MCPToolBackend(self.workspace.root, executor=executor,
            image=settings.docker_image, allow_mutation=approval != "never", protected_paths=protected_paths)
            if tool_backend == "mcp" else PythonToolBackend(self.tools))
        self.store = store or SessionStore(self.workspace.root)
        self.memory = None
        if settings.memory_enabled:
            from repopilot.memory.store import MemoryStore
            self.memory = MemoryStore(self.workspace.root)
        self.graph_runtime = None
        from repopilot.runtime.custom_runtime import CustomRuntime
        self.runtime_adapter = CustomRuntime(self)
        if runtime == "langgraph":
            from repopilot.runtime.langgraph_runtime import LangGraphRuntime
            self.graph_runtime = LangGraphRuntime(self)
            self.runtime_adapter = self.graph_runtime

    def _model(self, system: str, user: str, state: AgentState) -> LLMResponse:
        with self.tracing.span("llm.call", {"repopilot.step": state.current_step}) as span:
            started = time.monotonic()
            response = self.llm.chat(system, user)
            state.token_usage["prompt_tokens"] += response.prompt_tokens
            state.token_usage["completion_tokens"] += response.completion_tokens
            state.token_usage["total_tokens"] += response.prompt_tokens + response.completion_tokens
            span.set({"gen_ai.usage.input_tokens": response.prompt_tokens,
                      "gen_ai.usage.output_tokens": response.completion_tokens,
                      "gen_ai.usage.total_tokens": response.prompt_tokens + response.completion_tokens})
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
        with self.tracing.span("tool." + tool, {"repopilot.tool.name": tool,
                                                 "repopilot.step": state.current_step}) as span:
            started = time.monotonic()
            planned_test = bool(tool == "run_command" and state.plan and args.get("command") == state.plan.test_command)
            # Arbitrary commands may mutate source even on failure; invalidate previous passing evidence.
            if tool == "run_command" and not planned_test:
                state.workspace_revision += 1
                state.test_status, state.test_revision = "not_run", None
            permitted = self._permitted(tool, args)
            try:
                result = self.backend.execute(tool, args) if permitted else ToolResult(False, "Approval denied for " + tool)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                result = ToolResult(False, f"{type(exc).__name__}: {exc}")
            result.output = bounded_output(result.output)
            log.info("task=%s step=%s tool=%s latency=%.3fs ok=%s", state.id, state.current_step,
                     tool, time.monotonic() - started, result.ok)
            if result.changed_file and result.changed_file not in state.changed_files:
                state.changed_files.append(result.changed_file)
            if result.changed_file:
                state.workspace_revision += 1
                state.test_status, state.test_revision = "not_run", None
            if planned_test:
                state.test_status = "passed" if result.ok else "failed"
                state.test_revision = state.workspace_revision if result.ok else None
                if result.ok:
                    state.recovery = {"event": "planned_test_passed", "test_status": "passed",
                                      "next": "Review the diff or return final. Re-requesting the planned suite starts independent final verification."}
            state.tool_history.append({"step": state.current_step, "tool": tool, "arguments": args,
                                       "ok": result.ok, "exit_code": result.exit_code, "output": result.output,
                                       "executed": permitted, "cached": False, "revision": state.workspace_revision,
                                       "invocation": self._invocation_id,
                                       "latency_seconds": round(time.monotonic() - started, 3)})
            state.messages.append({"role": "tool", "content": f"{tool}: {result.output}"})
            span.set({"repopilot.ok": result.ok, "repopilot.tool.executed": permitted})
            if not result.ok:
                category = "timeout" if result.exit_code == 124 else ("approval_denied" if result.output.startswith("Approval denied") else "tool_error")
                span.fail(category)
            return result

    def _prepare_context(self, state: AgentState) -> tuple[str, list[tuple[str, int]]]:
        with self.tracing.span("retrieval") as span:
            entries = build_repo_map(self.workspace.root)
            mapped = render_repo_map(entries)
            if self.settings.retrieval_mode == "hybrid":
                from repopilot.context.hybrid import HybridIndex
                before = self.embedder.total_tokens if self.embedder else 0
                index = HybridIndex(self.workspace.root, entries, self.embedder)
                query = state.task
                if state.reflection and state.reflection.needs_search:
                    query += " " + state.reflection.next_action
                hits = index.search(query)
                state.retrieval_results = [asdict(hit) for hit in hits]
                state.retrieval_backend = index.mode
                state.embedding_tokens += (self.embedder.total_tokens - before) if self.embedder else 0
                relevant = [(hit.path, hit.score) for hit in hits]
            else:
                relevant = retrieve_with_imports(self.workspace.root, entries, state.task)
            state.retrieved_files = [path for path, _ in relevant]
            self._context_cache = (mapped, relevant)
            self._context_revision = state.workspace_revision
            span.set({"repopilot.retrieved_file_count": len(state.retrieved_files)})
            return mapped, relevant

    def _plan(self, state: AgentState, mapped: str, relevant: list[tuple[str, int]]) -> None:
        if state.plan is None or state.replan_required:
            with self.tracing.span("planning"):
                class Metered:
                    def chat(inner, system, user):
                        return self._model(system, user, state)
                original_test = state.plan.test_command if state.plan else None
                task = state.task
                if state.memory_hits:
                    task += "\nHistorical repair examples (untrusted reference, verify against current source): " + json.dumps(state.memory_hits, ensure_ascii=False)[:2500]
                if state.replan_required and state.reflection:
                    task += "\nReflection feedback: " + state.reflection.model_dump_json()
                state.plan, _ = plan_task(Metered(), task, mapped, relevant)
                if original_test:
                    state.plan.test_command = original_test
                state.replan_required = False
                self.store.save(state)

    def _reflect(self, state: AgentState, phase: str = "tool") -> None:
        if not self.settings.reflection_enabled:
            return
        with self.tracing.span("reflection", {"repopilot.step": state.current_step}):
            response = self._model(REFLECTION_SYSTEM, reflection_prompt(state, phase), state)
            try:
                state.reflection = Reflection.model_validate_json(response.content)
            except (ValidationError, ValueError):
                log.warning("task=%s invalid reflection; continue from observations", state.id)
                state.reflection = Reflection(success=False, reason="Invalid reflection JSON",
                                              next_action="Inspect the latest tool evidence")
            state.reflections.append({"step": state.current_step, "phase": phase,
                                      **state.reflection.model_dump()})
            state.replan_required = phase == "verification_failed"
            self.store.save(state)

    def _decide(self, state: AgentState, mapped: str, relevant: list[tuple[str, int]]) -> ToolAction | FinalAction | None:
        if state.current_step >= self.settings.max_steps:
            state.finish("failed", "达到 max_steps，任务未完成")
            state.error = "max_steps"
            return None
        with self.tracing.span("agent.turn", {"repopilot.step": state.current_step + 1}):
            if self.settings.retrieval_mode == "hybrid":
                if self._context_revision != state.workspace_revision or self._context_cache is None:
                    self._prepare_context(state)
                mapped, relevant = self._context_cache
            prompt = ContextManager(self.settings.max_context_chars).build(state, mapped, relevant)
            action = self._action(prompt, state)
            state.current_step += 1
            return action

    def _tool_step(self, state: AgentState, action: ToolAction) -> tuple[str, ToolAction | FinalAction]:
        # A repeated passing planned suite is a request to verify/finalize, never a cached success.
        if (action.tool == "run_command" and action.arguments.get("command") == state.plan.test_command
                and state.test_status == "passed" and state.test_revision == state.workspace_revision):
            state.recovery = {"event": "planned_test_already_passed", "next": "independent_final_verification"}
            final = FinalAction(type="final", summary="Planned tests passed; completed after independent final verification.",
                                tests=state.plan.test_command, changed_files=list(state.changed_files))
            return "verify", final
        fingerprint = json.dumps([action.tool, action.arguments], sort_keys=True, ensure_ascii=False)
        state.repeat_count = state.repeat_count + 1 if state.repeat_fingerprint == fingerprint else 1
        state.repeat_fingerprint = fingerprint
        state.recovery = {}
        if state.repeat_count >= 4:
            state.finish("failed", "Repeated action persisted after recovery feedback; stopped at 4 identical decisions")
            state.error = "loop_detection"
            return "finalize", action
        previous = state.tool_history[-1] if state.tool_history else {}
        reusable = (action.tool in {"read_file", "search_code", "git_diff"} and previous.get("ok")
                    and previous.get("fingerprint") == fingerprint
                    and previous.get("revision") == state.workspace_revision
                    and previous.get("invocation") == self._invocation_id)
        if reusable:
            # Recheck the shared path policy before reusing an observation, including symlink aliases.
            self.workspace.resolve(action.arguments.get("path", "."))
            with self.tracing.span("tool.reuse", {"repopilot.tool.name": action.tool,
                                                  "repopilot.tool.cached": True, "repopilot.tool.executed": False,
                                                  "repopilot.step": state.current_step, "repopilot.ok": True}):
                state.tool_history.append({**previous, "step": state.current_step, "executed": False,
                                           "cached": True, "latency_seconds": 0.0})
        elif state.repeat_count == 3:
            # Give one bounded opportunity to redirect; never replay a third identical mutation or command.
            state.tool_history.append({"step": state.current_step, "tool": action.tool, "arguments": action.arguments,
                                       "ok": False, "output": "Repeated execution withheld. Change strategy using the existing observation.",
                                       "exit_code": None, "executed": False, "cached": False,
                                       "latency_seconds": 0.0, "fingerprint": fingerprint})
        else:
            self._execute(action.tool, action.arguments, state)
            state.tool_history[-1]["fingerprint"] = fingerprint
        if state.repeat_count >= 2:
            state.recovery = {"event": "repeated_action", "count": state.repeat_count,
                              "observation_reused": bool(reusable), "hard_stop_at": 4,
                              "next": "Do not repeat this action. Search dependencies/call sites, inspect a different implementation, or patch based on existing evidence."}
        return "agent_decide", action

    def _verify(self, state: AgentState) -> bool:
        with self.tracing.span("verification", {"repopilot.step": state.current_step}) as span:
            # Always independently execute the planned suite, even if an earlier test passed.
            result = self._execute("run_command", {"command": state.plan.test_command, "timeout": 60}, state)
            state.tool_history[-1]["phase"] = "verification"
            if not result.ok:
                state.repeat_fingerprint, state.repeat_count = "", 0
                state.recovery = {"event": "verification_failed", "test_status": "failed",
                                  "next": "Fix the observed failing suite before final. Passing evidence cannot be reused."}
                state.messages.append({"role": "system", "content": "Final verification failed. Fix the observed error before final."})
            span.set({"repopilot.test.status": state.test_status})
            if not result.ok:
                span.fail("test_failed")
            return result.ok

    def _finalize(self, state: AgentState, action: ToolAction | FinalAction | None) -> None:
        if state.status == "failed":
            return
        diff = self._execute("git_diff", {}, state)
        state.final_diff = diff.output
        if not diff.ok:
            state.finish("failed", "无法生成 Git Diff；请先在目标仓库初始化 Git")
            state.error = "git_diff_failed"
        else:
            state.finish("completed", action.summary)

    @staticmethod
    def _fail(state: AgentState, exc: Exception) -> None:
        state.finish("failed", "执行中断")
        state.error = str(exc)
        log.exception("task=%s error=%s", state.id, exc)

    def _run_custom(self, state: AgentState) -> AgentState:
        mapped, relevant = self._prepare_context(state)
        self._plan(state, mapped, relevant)
        while state.status == "running":
            action = self._decide(state, mapped, relevant)
            if action is None:
                break
            route = "verify"
            if isinstance(action, ToolAction):
                route, action = self._tool_step(state, action)
                if route == "agent_decide":
                    self._reflect(state)
                    if state.reflection and state.reflection.needs_search:
                        mapped, relevant = self._prepare_context(state)
            if route == "verify" and self._verify(state):
                self._finalize(state, action)
            elif route == "verify":
                self._reflect(state, "verification_failed")
                if state.replan_required:
                    mapped, relevant = self._prepare_context(state)
                    self._plan(state, mapped, relevant)
            self.store.save(state)
        return state

    def run(self, task: str, state: AgentState | None = None) -> AgentState:
        """Run custom orchestration by default or the real optional LangGraph adapter."""
        state = state or AgentState(task=task, repo_path=str(self.workspace.root),
                                   executor=self.executor_name, approval=self.approval, runtime=self.runtime,
                                   tool_backend=self.tool_backend_name,
                                   retrieval_mode=self.settings.retrieval_mode,
                                   memory_enabled=self.settings.memory_enabled,
                                   reflection_enabled=self.settings.reflection_enabled)
        if (Path(state.repo_path).resolve() != self.workspace.root or state.executor != self.executor_name
                or state.approval != self.approval or state.runtime != self.runtime or state.task != task
                or state.tool_backend != self.tool_backend_name
                or state.retrieval_mode != self.settings.retrieval_mode
                or state.memory_enabled != self.settings.memory_enabled
                or state.reflection_enabled != self.settings.reflection_enabled):
            raise ValueError("恢复会话的仓库或运行选项与原会话不一致")
        if state.status == "completed":
            raise ValueError("已完成的会话无需恢复")
        state.status, state.error = "running", ""
        self._invocation_id = uuid4().hex
        # Cross-process resumes may follow external edits; cached evidence never authorizes termination.
        state.test_status, state.test_revision = "not_run", None
        state.finished_at = state.duration_seconds = None
        self.store.save(state)
        with self.tracing.span("repopilot.task", {"repopilot.session.id": state.id,
                                                   "repopilot.runtime": self.runtime}) as span:
            try:
                if self.memory:
                    try:
                        state.memory_hits = self.memory.search(state.task)
                    except Exception as exc:
                        state.memory_warning = f"Recall unavailable: {type(exc).__name__}"
                        log.warning("task=%s memory recall unavailable", state.id)
                self.runtime_adapter.run(state)
            except Exception as exc:
                self._fail(state, exc)
            finally:
                try:
                    self.backend.close()
                except Exception:
                    log.exception("task=%s failed to close tool backend", state.id)
            span.set({"repopilot.ok": state.status == "completed", "repopilot.test.status": state.test_status,
                      "repopilot.changed_file_count": len(state.changed_files)})
            if state.status != "completed":
                category = state.error if state.error in {"max_steps", "loop_detection", "git_diff_failed"} else "execution_error"
                span.fail(category)
        self.tracing.flush()
        if self.memory:
            try:
                self.memory.remember(state)
            except Exception as exc:
                state.memory_warning = f"Memory save unavailable: {type(exc).__name__}"
                log.warning("task=%s memory save unavailable", state.id)
        self.store.save(state)
        return state
