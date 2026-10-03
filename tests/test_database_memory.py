"""Durability, relational audit, repository leases and evidence-based memory."""
import json
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as ORM

from repopilot.agent.agent import RepoPilot, demo_responses
from repopilot.agent.state import AgentState
from repopilot.config import Settings
from repopilot.database.models import Event, Session, Step, Task, TokenUsage, ToolCall
from repopilot.database.store import Database, sqlite_url
from repopilot.llm.base import FakeLLM
from repopilot.memory.store import MemoryStore
from repopilot.session.store import SessionStore


def test_normalized_audit_snapshot_and_idempotent_save(runtime_repo):
    agent = RepoPilot(runtime_repo, FakeLLM(demo_responses()), Settings(), executor="local", approval="auto")
    state = agent.run("fix")
    assert state.status == "completed"
    database = agent.store.database
    with ORM(database.engine) as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1
        assert db.scalar(select(func.count()).select_from(Session)) == 1
        assert db.scalar(select(func.count()).select_from(Step)) == state.current_step
        assert db.scalar(select(func.count()).select_from(ToolCall)) == len(state.tool_history)
        usage = db.get(TokenUsage, state.id)
        assert usage.total_tokens == state.token_usage["total_tokens"]
    before = len(database.events(state.id))
    database.save(state)
    assert len(database.events(state.id)) == before
    database.close()
    assert SessionStore(runtime_repo).load(state.id).model_dump() == state.model_dump()
    assert not list(agent.store.directory.glob("*.json"))


def test_legacy_json_import_validates_repo_and_preserves_current_db(runtime_repo):
    store = SessionStore(runtime_repo)
    old = AgentState(task="old task", repo_path=str(runtime_repo))
    store.path(old.id).write_text(old.model_dump_json(), encoding="utf-8")
    imported = store.load(old.id)
    imported.summary = "newer database state"
    store.save(imported)
    assert store.list()[0].summary == "newer database state"
    wrong = AgentState(task="wrong", repo_path=str(runtime_repo.parent))
    store.path(wrong.id).write_text(wrong.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="仓库"):
        store.load(wrong.id)


def test_database_repository_lease_claim_and_release(runtime_repo, tmp_path):
    database = Database(sqlite_url(tmp_path / "central.db"))
    first = AgentState(task="one", repo_path=str(runtime_repo))
    second = AgentState(task="two", repo_path=str(runtime_repo))
    database.create_task(first, {"runtime": "custom"})
    with pytest.raises(IntegrityError):
        database.create_task(second, {})
    assert database.claim(first.id) is True
    assert database.claim(first.id) is False
    first.finish("failed", "stopped")
    database.save(first)
    database.create_task(second, {})
    assert database.request(first.id) == {"runtime": "custom"}
    events = database.events(first.id)
    assert [event["id"] for event in events] == [1, 2, 3]
    assert [event["data"]["status"] for event in events] == ["pending", "running", "failed"]
    assert database.events(first.id, after=2)[0]["data"]["status"] == "failed"


def experience(repo, *, success=True):
    return AgentState(task="修复 duplicate email 注册错误", repo_path=str(repo),
                      summary="Map unique constraint to DuplicateEmailError", final_diff="ValueError -> DuplicateEmailError",
                      error="" if success else "test_failed", status="completed" if success else "failed",
                      test_status="passed" if success else "failed")


def test_memory_fts_persistence_deduplication_and_repo_isolation(runtime_repo, tmp_path):
    memory_path = tmp_path / "shared-memory.db"
    memory = MemoryStore(runtime_repo, memory_path)
    success = experience(runtime_repo)
    memory.remember(success)
    memory.remember(success)
    memory.remember(experience(runtime_repo, success=False))
    reopened = MemoryStore(runtime_repo, memory_path)
    hits = reopened.search("重复邮箱 email duplicate")
    assert len(hits) == 1 and hits[0]["session_id"] == success.id and hits[0]["verified"]
    other = MemoryStore(tmp_path, memory_path)
    assert other.search("duplicate email") == []
    assert reopened.search('" OR * --') == []
    reopened.fts = False
    assert reopened.search("duplicate email")[0]["session_id"] == success.id


def test_memory_never_recalls_unverified_completion(runtime_repo):
    memory = MemoryStore(runtime_repo)
    state = experience(runtime_repo)
    state.test_status = "not_run"
    memory.remember(state)
    assert memory.search("duplicate email") == []


def test_agent_automatically_uses_and_records_memory(runtime_repo):
    memory = MemoryStore(runtime_repo)
    old = experience(runtime_repo)
    memory.remember(old)

    class RecordingLLM(FakeLLM):
        prompts = []

        def chat(self, system, user):
            self.prompts.append(user)
            return super().chat(system, user)

    model = RecordingLLM(demo_responses())
    result = RepoPilot(runtime_repo, model, Settings(memory_enabled=True),
                       executor="local", approval="auto").run("fix duplicate email")
    assert result.status == "completed" and result.memory_hits[0]["session_id"] == old.id
    assert any("Historical repair" in prompt and old.summary in prompt for prompt in model.prompts)
    assert len(memory.search("duplicate email")) == 2


def test_database_path_symlink_rejected(runtime_repo, tmp_path):
    (runtime_repo / ".repopilot").mkdir()
    (runtime_repo / ".repopilot/repopilot.db").symlink_to(tmp_path / "outside.db")
    with pytest.raises(ValueError):
        SessionStore(runtime_repo)
