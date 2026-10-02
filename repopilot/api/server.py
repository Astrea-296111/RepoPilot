"""Persistent asynchronous task API with replayable server-sent events."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import logging
import os
from pathlib import Path
import time
from typing import AsyncIterator, Callable, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from repopilot.agent.agent import RepoPilot
from repopilot.agent.state import AgentState
from repopilot.config import Settings
from repopilot.database.store import Database, TERMINAL, sqlite_url
from repopilot.llm.base import LLM
from repopilot.llm.openai_compatible import OpenAICompatibleLLM
from repopilot.session.store import SessionStore
from .queue import LocalTaskQueue, RedisTaskQueue
from .tasks import TaskService

log = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    repo_path: str
    task: str = Field(min_length=1, max_length=4000)
    executor: str = "docker"
    approval: str = "never"
    runtime: Literal["custom", "langgraph"] = "custom"
    tool_backend: Literal["python", "mcp"] = "python"
    retrieval: Literal["legacy", "hybrid"] = "legacy"
    reflection: bool = False
    memory: bool = False


def task_settings(request: TaskRequest) -> Settings:
    return Settings.load().model_copy(update={"reflection_enabled": request.reflection,
        "retrieval_mode": request.retrieval, "memory_enabled": request.memory})


def checked_repo(request: TaskRequest) -> Path:
    base = Path(os.environ.get("REPOPILOT_API_ROOT", Path.cwd())).resolve()
    repo = Path(request.repo_path).resolve()
    if not repo.is_dir() or not repo.is_relative_to(base):
        raise HTTPException(400, "Repository must be a directory under REPOPILOT_API_ROOT")
    if request.executor not in {"docker", "local"} or request.approval not in {"auto", "never"}:
        raise HTTPException(400, "Invalid executor or approval; API does not support interactive ask")
    if request.executor == "local" and os.getenv("REPOPILOT_API_ALLOW_LOCAL") != "1":
        raise HTTPException(400, "Local API execution disabled; set REPOPILOT_API_ALLOW_LOCAL=1 for trusted repos")
    return repo


def create_app(*, database_url: str | None = None, redis_url: str | None = None,
               llm_factory: Callable[[Settings], LLM] | None = None,
               workers: int = 2, capacity: int = 100) -> FastAPI:
    if not 1 <= workers <= 16 or capacity < 1:
        raise ValueError("workers must be 1–16 and capacity must be positive")
    make_llm = llm_factory or (lambda settings: OpenAICompatibleLLM(settings))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        url = database_url or os.getenv("REPOPILOT_DATABASE_URL")
        if not url:
            root = Path(os.environ.get("REPOPILOT_API_ROOT", Path.cwd())).resolve()
            directory = root / ".repopilot"
            if not directory.resolve().is_relative_to(root):
                raise ValueError("API database directory escapes root")
            directory.mkdir(parents=True, exist_ok=True)
            url = sqlite_url(directory / "api.db")
        database = await asyncio.to_thread(Database, url)
        queue_url = redis_url if redis_url is not None else os.getenv("REPOPILOT_REDIS_URL", "")
        namespace = "repopilot:" + hashlib.sha256(str(database.engine.url).encode()).hexdigest()[:16]
        queue = RedisTaskQueue(queue_url, capacity, namespace) if queue_url else LocalTaskQueue(capacity)

        def execute(payload: dict, state: AgentState) -> None:
            request = TaskRequest.model_validate(payload)
            repo = checked_repo(request)  # Revalidate after queue wait / filesystem changes.
            settings = task_settings(request)
            agent = RepoPilot(repo, make_llm(settings), settings, executor=request.executor,
                approval=request.approval, runtime=request.runtime, tool_backend=request.tool_backend,
                store=SessionStore(repo, database))
            agent.run(state.task, state)

        service = TaskService(database, queue, execute, workers, capacity)
        try:
            await service.start()
            application.state.tasks = service
            yield
        finally:
            await service.close()
            database.close()

    application = FastAPI(title="RepoPilot", version="0.2.0", lifespan=lifespan)

    @application.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    def service(request: Request) -> TaskService:
        tasks = getattr(request.app.state, "tasks", None)
        if tasks is None:
            raise HTTPException(503, "Task service has not started")
        return tasks

    @application.post("/api/tasks", status_code=202)
    async def start(payload: TaskRequest, request: Request) -> dict:
        repo = checked_repo(payload)
        settings = task_settings(payload)
        try:
            if payload.runtime == "langgraph":
                from repopilot.runtime.langgraph_runtime import LangGraphRuntime  # noqa: F401
            if payload.tool_backend == "mcp":
                import mcp  # noqa: F401
            if payload.retrieval == "hybrid":
                import faiss  # noqa: F401
                import rank_bm25  # noqa: F401
            make_llm(settings)  # Validate configuration without making a provider call.
        except (ValueError, ImportError) as exc:
            raise HTTPException(400, str(exc)) from exc
        state = AgentState(task=payload.task, repo_path=str(repo), executor=payload.executor,
            approval=payload.approval, runtime=payload.runtime, tool_backend=payload.tool_backend,
            reflection_enabled=payload.reflection, retrieval_mode=payload.retrieval, memory_enabled=payload.memory)
        try:
            await service(request).submit(payload.model_dump(), state)
        except IntegrityError as exc:
            raise HTTPException(409, "Repository already has an active task") from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"task_id": state.id, "id": state.id, "status": "pending"}

    async def load(request: Request, task_id: str) -> AgentState:
        if len(task_id) != 32 or any(char not in "0123456789abcdef" for char in task_id):
            raise HTTPException(404, "Unknown task ID")
        try:
            state = await asyncio.to_thread(service(request).database.load, task_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Unknown task ID") from exc
        base = Path(os.environ.get("REPOPILOT_API_ROOT", Path.cwd())).resolve()
        if not Path(state.repo_path).resolve().is_relative_to(base):
            raise HTTPException(404, "Task is outside the configured API root")
        return state

    @application.get("/api/tasks/{task_id}")
    async def get_task(task_id: str, request: Request) -> dict:
        state = await load(request, task_id)
        return {**state.model_dump(mode="json"), "task_id": state.id,
                "steps": state.current_step, "logs": state.tool_history}

    @application.get("/api/tasks/{task_id}/stream")
    async def stream(task_id: str, request: Request, after: int = Query(0, ge=0),
                     last_event_id: str | None = Header(None)) -> StreamingResponse:
        await load(request, task_id)
        try:
            cursor = int(last_event_id) if last_event_id is not None else after
            if cursor < 0:
                raise ValueError()
        except ValueError as exc:
            raise HTTPException(400, "Last-Event-ID must be a nonnegative integer") from exc
        database = service(request).database

        async def events() -> AsyncIterator[str]:
            nonlocal cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                batch = await asyncio.to_thread(database.events, task_id, cursor)
                for item in batch:
                    cursor = item["id"]
                    yield f"id: {cursor}\nevent: task\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
                if batch:
                    continue  # Drain persisted batches before emitting end.
                state = await asyncio.to_thread(database.load, task_id)
                if state.status in TERMINAL:
                    # A terminal save may have committed after the first event read.
                    if await asyncio.to_thread(database.events, task_id, cursor, 1):
                        continue
                    yield f"event: end\ndata: {json.dumps({'status': state.status})}\n\n"
                    return
                if time.monotonic() - heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.2)

        return StreamingResponse(events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return application


app = create_app()
