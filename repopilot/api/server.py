"""Small asynchronous REST entry point; task state is persisted per repo."""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field
from repopilot.agent.agent import RepoPilot
from repopilot.agent.state import AgentState
from repopilot.config import Settings
from repopilot.llm.openai_compatible import OpenAICompatibleLLM
from repopilot.session.store import SessionStore

app = FastAPI(title="RepoPilot", version="0.1.0")
TASKS: dict[str, Path] = {}  # in-memory lookup; transcript itself is on disk


class TaskRequest(BaseModel):
    repo_path: str
    task: str = Field(min_length=1, max_length=4000)
    executor: str = "docker"
    approval: str = "never"  # non-interactive API cannot ask a human


@app.get("/health")
def health(): return {"status": "ok"}


def _run(request: TaskRequest, state: AgentState, repo: Path):
    try:
        agent = RepoPilot(repo, OpenAICompatibleLLM(Settings.load()), Settings.load(),
                          executor=request.executor, approval=request.approval)
        agent.run(state.task, state)
    except Exception as exc:
        state.error = str(exc)
        state.finish("failed", "任务初始化失败")
        SessionStore(repo).save(state)


@app.post("/api/tasks", status_code=202)
def start(request: TaskRequest, background_tasks: BackgroundTasks):
    base = Path(os.environ.get("REPOPILOT_API_ROOT", Path.cwd())).resolve()
    repo = Path(request.repo_path).resolve()
    if not repo.is_dir() or not repo.is_relative_to(base):
        raise HTTPException(400, "Repository must be a directory under REPOPILOT_API_ROOT")
    if request.executor not in {"docker", "local"} or request.approval not in {"auto", "never"}:
        raise HTTPException(400, "Invalid executor or approval; API does not support interactive ask")
    if request.executor == "local" and os.getenv("REPOPILOT_API_ALLOW_LOCAL") != "1":
        raise HTTPException(400, "Local API execution disabled; set REPOPILOT_API_ALLOW_LOCAL=1 for trusted repos")
    try: OpenAICompatibleLLM(Settings.load())
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    state = AgentState(task=request.task, repo_path=str(repo), executor=request.executor, approval=request.approval)
    SessionStore(repo).save(state)
    TASKS[state.id] = repo
    background_tasks.add_task(_run, request, state, repo)
    return {"id": state.id, "status": state.status}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    repo = TASKS.get(task_id)
    if repo is None: raise HTTPException(404, "Unknown task ID on this API process")
    return SessionStore(repo).load(task_id)

