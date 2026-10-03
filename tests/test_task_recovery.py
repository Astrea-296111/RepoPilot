"""Fault injection at task ownership, durable settlement and acknowledgement."""
import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from repopilot.agent.state import AgentState
from repopilot.api.queue import LocalTaskQueue
from repopilot.api.tasks import TaskService
from repopilot.database.models import Task
from repopilot.database.store import Database, sqlite_url


@pytest.fixture
def inline_database_io(monkeypatch: pytest.MonkeyPatch) -> None:
    # These tests control task interleavings rather than the thread pool. Real
    # to_thread and HTTP execution remain covered by API/service integration tests.
    async def execute(function: Any, /, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", execute)


async def wait_for(predicate: Any) -> None:
    async with asyncio.timeout(6):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("method", ["load", "request"])
def test_read_failure_redelivers_without_stranding_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inline_database_io: None, method: str,
) -> None:
    async def exercise() -> None:
        database = Database(sqlite_url(tmp_path / "tasks.db"))
        queue = LocalTaskQueue()
        calls: list[str] = []
        original = getattr(database, method)
        failed = False

        def fail_once(task_id: str) -> Any:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("transient read failure")
            return original(task_id)

        def runner(request: dict, state: AgentState) -> None:
            calls.append(state.id)
            state.finish("completed", "done")

        monkeypatch.setattr(database, method, fail_once)
        service = TaskService(database, queue, runner, workers=2)
        await service.start()
        state = AgentState(task="recover", repo_path=str(tmp_path))
        try:
            await service.submit({}, state)
            await wait_for(lambda: Database.load(database, state.id).status == "completed" and not queue.known)
            assert calls == [state.id]
            with Session(database.engine) as db:
                row = db.get(Task, state.id)
                assert row.status == "completed" and row.active_repo is None
            # The same repository is available again without restarting the API.
            next_state = AgentState(task="next", repo_path=str(tmp_path))
            await service.submit({}, next_state)
            await wait_for(lambda: database.load(next_state.id).status == "completed")
        finally:
            await service.close()
            database.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("committed", [False, True])
def test_uncertain_claim_is_interrupted_without_running_or_replaying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inline_database_io: None, committed: bool,
) -> None:
    async def exercise() -> None:
        database = Database(sqlite_url(tmp_path / "claim.db"))
        queue = LocalTaskQueue()
        calls: list[str] = []
        original_claim = database.claim

        def uncertain_claim(task_id: str) -> bool:
            if committed:
                assert original_claim(task_id)
                assert database.load(task_id).status == "running"
                assert database.events(task_id)[-1]["data"]["status"] == "running"
            raise OSError("claim commit response lost")

        monkeypatch.setattr(database, "claim", uncertain_claim)
        service = TaskService(database, queue, lambda request, state: calls.append(state.id), workers=2)
        await service.start()
        state = AgentState(task="ambiguous", repo_path=str(tmp_path))
        try:
            await service.submit({}, state)
            await wait_for(lambda: database.load(state.id).status == "interrupted" and not queue.known)
            assert calls == []
            assert database.load(state.id).error == "claim_outcome_uncertain"
            with Session(database.engine) as db:
                assert db.get(Task, state.id).active_repo is None
        finally:
            await service.close()
            database.close()
    asyncio.run(exercise())


def test_terminal_save_and_ack_retry_without_reexecuting_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inline_database_io: None,
) -> None:
    async def exercise() -> None:
        database = Database(sqlite_url(tmp_path / "settle.db"))
        queue = LocalTaskQueue()
        calls: list[str] = []
        original_save, original_ack = database.save, queue.ack
        saves = acknowledgements = 0

        def save(state: AgentState) -> None:
            nonlocal saves
            saves += 1
            if saves == 1:
                raise OSError("terminal save temporarily unavailable")
            original_save(state)

        async def ack(task_id: str) -> None:
            nonlocal acknowledgements
            acknowledgements += 1
            assert database.load(task_id).status == "failed"
            if acknowledgements == 1:
                raise OSError("ack temporarily unavailable")
            await original_ack(task_id)

        def runner(request: dict, state: AgentState) -> None:
            calls.append(state.id)
            raise ValueError("runner failed after a possible side effect")

        monkeypatch.setattr(database, "save", save)
        monkeypatch.setattr(queue, "ack", ack)
        service = TaskService(database, queue, runner, workers=2)
        await service.start()
        state = AgentState(task="settle", repo_path=str(tmp_path))
        try:
            await service.submit({}, state)
            await wait_for(lambda: not queue.known)
            assert calls == [state.id] and saves == acknowledgements == 2
            # A stale outbox snapshot can redeliver; SQL prevents another runner call.
            await queue.enqueue(state.id)
            await wait_for(lambda: not queue.known)
            assert calls == [state.id]
            with Session(database.engine) as db:
                assert db.get(Task, state.id).active_repo is None
        finally:
            await service.close()
            database.close()
    asyncio.run(exercise())
