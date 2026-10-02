"""Transactional snapshots plus normalized audit rows and replayable SSE events."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session as ORMSession
from sqlalchemy.pool import NullPool, StaticPool

from repopilot.agent.state import AgentState
from .models import Base, Event, Session, Step, Task, TokenUsage, ToolCall

log = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "interrupted", "cancelled"}


def sqlite_url(path: Path) -> str:
    return URL.create("sqlite", database=str(path.resolve())).render_as_string(hide_password=False)


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs.update(connect_args={"check_same_thread": False, "timeout": 30},
                          poolclass=StaticPool if url in {"sqlite://", "sqlite:///:memory:"} else NullPool)
        self.engine = create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def configure(connection: Any, _: Any) -> None:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _task(state: AgentState, *, active: bool = False, request: dict | None = None) -> Task:
        return Task(id=state.id, repo=state.repo_path, task=state.task, status=state.status,
                    active_repo=hashlib.sha256(state.repo_path.encode()).hexdigest() if active else None,
                    request=request or {}, updated_at=time.time())

    def create_task(self, state: AgentState, request: dict) -> None:
        """Unique repository lease and initial state commit atomically."""
        with ORMSession(self.engine) as db, db.begin():
            db.add(self._task(state, active=True, request=request))
            db.flush()
            self._save(db, state)

    def save(self, state: AgentState) -> None:
        with ORMSession(self.engine) as db, db.begin():
            task = db.get(Task, state.id)
            if task is None:
                db.add(self._task(state))
                db.flush()
            self._save(db, state)

    def _save(self, db: ORMSession, state: AgentState) -> None:
        snapshot = state.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        record = db.get(Session, state.id)
        if record is not None and record.fingerprint == fingerprint:
            return
        revision = (record.revision if record else 0) + 1
        if record is None:
            record = Session(id=state.id, snapshot=snapshot, fingerprint=fingerprint, revision=revision)
            db.add(record)
        else:
            record.snapshot, record.fingerprint, record.revision = snapshot, fingerprint, revision
        db.flush()
        task = db.get(Task, state.id)
        task.status, task.updated_at = state.status, time.time()
        if state.status in TERMINAL:
            task.active_repo = None
        existing_steps = set(db.scalars(select(Step.number).where(Step.session_id == state.id)))
        actions = [message["content"] for message in state.messages if message.get("role") == "assistant"]
        for number in range(1, state.current_step + 1):
            if number not in existing_steps:
                try:
                    action = json.loads(actions[number - 1])
                except (IndexError, ValueError):
                    action = {"note": "Imported session without action transcript"}
                db.add(Step(session_id=state.id, number=number, action=action))
        existing_calls = set(db.scalars(select(ToolCall.number).where(ToolCall.session_id == state.id)))
        for number, item in enumerate(state.tool_history, 1):
            if number not in existing_calls:
                db.add(ToolCall(session_id=state.id, number=number, step=item["step"], tool=item["tool"],
                                arguments=item["arguments"], result={k: v for k, v in item.items() if k != "arguments"}))
        db.merge(TokenUsage(session_id=state.id, **state.token_usage, embedding_tokens=state.embedding_tokens))
        previous_tools = len(existing_calls)
        data = {"status": state.status, "steps": state.current_step, "test_status": state.test_status,
                "error": state.error, "summary": state.summary,
                "logs": state.tool_history[previous_tools:],
                "reflection": state.reflection.model_dump() if state.reflection else None}
        db.add(Event(task_id=state.id, sequence=revision, data=data, created_at=time.time()))
        log.debug("persist task=%s revision=%s status=%s", state.id, revision, state.status)

    def load(self, task_id: str) -> AgentState:
        with ORMSession(self.engine) as db:
            record = db.get(Session, task_id)
            if record is None:
                raise FileNotFoundError("Unknown task ID")
            return AgentState.model_validate(record.snapshot)

    def list(self, repo: str | None = None, statuses: set[str] | None = None) -> list[AgentState]:
        query = select(Session).join(Task, Task.id == Session.id).order_by(Task.updated_at.desc())
        if repo is not None:
            query = query.where(Task.repo == repo)
        if statuses:
            query = query.where(Task.status.in_(statuses))
        with ORMSession(self.engine) as db:
            return [AgentState.model_validate(record.snapshot) for record in db.scalars(query)]

    def request(self, task_id: str) -> dict:
        with ORMSession(self.engine) as db:
            task = db.get(Task, task_id)
            if task is None:
                raise FileNotFoundError(task_id)
            return dict(task.request)

    def claim(self, task_id: str) -> bool:
        """Atomic pending→running claim deduplicates repeated queue deliveries."""
        with ORMSession(self.engine) as db, db.begin():
            result = db.execute(update(Task).where(Task.id == task_id, Task.status == "pending")
                                .values(status="running", updated_at=time.time()))
            return result.rowcount == 1

    def events(self, task_id: str, after: int = 0, limit: int = 100) -> list[dict]:
        with ORMSession(self.engine) as db:
            rows = db.scalars(select(Event).where(Event.task_id == task_id, Event.sequence > after)
                              .order_by(Event.sequence).limit(limit))
            return [{"id": row.sequence, "data": row.data} for row in rows]

    def close(self) -> None:
        self.engine.dispose()
