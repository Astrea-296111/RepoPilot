"""Portable SQLAlchemy schema shared by SQLite development and PostgreSQL service."""
from __future__ import annotations

from typing import Any
from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    repo: Mapped[str] = mapped_column(Text)
    task: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), index=True)
    # Nullable unique key: at most one queued/running API task per repository.
    active_repo: Mapped[str | None] = mapped_column(String(64), unique=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[float] = mapped_column(Float)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(default=0)


class Step(Base):
    __tablename__ = "steps"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[dict[str, Any]] = mapped_column(JSON)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    step: Mapped[int]
    tool: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class TokenUsage(Base):
    __tablename__ = "token_usage"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    prompt_tokens: Mapped[int]
    completion_tokens: Mapped[int]
    total_tokens: Mapped[int]
    embedding_tokens: Mapped[int]


class Event(Base):
    __tablename__ = "task_events"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    sequence: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
