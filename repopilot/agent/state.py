"""Persistent, serializable state for an agent task."""
from __future__ import annotations
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field


class Plan(BaseModel):
    goal: str
    suspected_files: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    test_command: str = "pytest -q"


class AgentState(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    task: str
    repo_path: str
    executor: str = "docker"
    approval: str = "ask"
    plan: Plan | None = None
    current_step: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    retrieved_files: list[str] = Field(default_factory=list)
    test_status: str = "not_run"
    token_usage: dict[str, int] = Field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    status: str = "pending"
    summary: str = ""
    final_diff: str = ""
    error: str = ""
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    duration_seconds: float | None = None

    def finish(self, status: str, summary: str = "") -> None:
        self.status = status
        if summary: self.summary = summary
        finished = datetime.now(timezone.utc)
        self.finished_at = finished.isoformat()
        self.duration_seconds = round((finished - datetime.fromisoformat(self.started_at)).total_seconds(), 3)
        logging.getLogger(__name__).info("task=%s status=%s steps=%s changed_files=%s duration=%.3fs",
                                         self.id, status, self.current_step, self.changed_files, self.duration_seconds)
