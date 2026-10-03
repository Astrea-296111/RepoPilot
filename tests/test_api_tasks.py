"""Async acceptance, durable queries, SSE replay, queue recovery and repo exclusion."""
import asyncio
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest

from repopilot.agent.agent import demo_responses
from repopilot.agent.state import AgentState
from repopilot.api.queue import LocalTaskQueue
from repopilot.api.server import create_app, TaskRequest
from repopilot.database.store import Database, sqlite_url
from repopilot.llm.base import FakeLLM


def payload(repo, **options):
    return {"repo_path": str(repo), "task": "fix duplicate email", "executor": "local", "approval": "auto", **options}


def wait_done(client, task_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = client.get(f"/api/tasks/{task_id}").json()
        if value["status"] in {"completed", "failed", "interrupted"}:
            return value
        time.sleep(0.05)
    raise AssertionError("Task did not finish")


@pytest.fixture
def api_environment(runtime_repo, monkeypatch):
    monkeypatch.setenv("REPOPILOT_API_ROOT", str(runtime_repo.parent))
    monkeypatch.setenv("REPOPILOT_API_ALLOW_LOCAL", "1")
    monkeypatch.delenv("REPOPILOT_DATABASE_URL", raising=False)
    monkeypatch.delenv("REPOPILOT_REDIS_URL", raising=False)


def test_async_acceptance_conflict_persistence_and_sse(runtime_repo, tmp_path, api_environment):
    gate = threading.Event()

    class SlowModel(FakeLLM):
        def chat(self, system, user):
            assert gate.wait(20), "test gate timed out"
            return super().chat(system, user)

    url = sqlite_url(tmp_path / "api.db")
    app = create_app(database_url=url, llm_factory=lambda _: SlowModel(demo_responses()))
    with TestClient(app) as client:
        try:
            started = time.monotonic()
            response = client.post("/api/tasks", json=payload(runtime_repo))
            assert response.status_code == 202 and time.monotonic() - started < 3
            task_id = response.json()["task_id"]
            assert client.get(f"/api/tasks/{task_id}").json()["status"] in {"pending", "running"}
            assert client.post("/api/tasks", json=payload(runtime_repo)).status_code == 409
        finally:
            gate.set()
        result = wait_done(client, task_id)
        assert result["status"] == "completed" and result["steps"] == 6 and result["logs"]
        events = client.get(f"/api/tasks/{task_id}/stream")
        assert events.headers["content-type"].startswith("text/event-stream")
        ids = [int(line[4:]) for line in events.text.splitlines() if line.startswith("id: ")]
        assert ids == sorted(set(ids)) and len(ids) > 3
        assert '"status": "completed"' in events.text and "event: end" in events.text
        replay = client.get(f"/api/tasks/{task_id}/stream", headers={"Last-Event-ID": str(ids[-2])})
        assert [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")] == [ids[-1]]
        assert client.get(f"/api/tasks/{task_id}/stream", headers={"Last-Event-ID": "bad"}).status_code == 400
        assert client.get("/api/tasks/unknown").status_code == 404
    with TestClient(create_app(database_url=url, llm_factory=lambda _: FakeLLM([]))) as client:
        assert client.get(f"/api/tasks/{task_id}").json()["status"] == "completed"


def test_restart_recovers_pending_but_never_replays_claimed_task(runtime_repo, tmp_path, api_environment):
    url = sqlite_url(tmp_path / "restart.db")
    database = Database(url)
    old = AgentState(task="abandoned", repo_path=str(tmp_path), executor="local", approval="auto")
    database.create_task(old, payload(tmp_path))
    assert database.claim(old.id)
    pending = AgentState(task="fix duplicate email", repo_path=str(runtime_repo), executor="local", approval="auto")
    database.create_task(pending, payload(runtime_repo))
    database.close()
    with TestClient(create_app(database_url=url, llm_factory=lambda _: FakeLLM(demo_responses()))) as client:
        interrupted = client.get(f"/api/tasks/{old.id}").json()
        assert interrupted["status"] == "interrupted" and interrupted["steps"] == 0
        assert wait_done(client, pending.id)["status"] == "completed"


def test_capacity_is_bounded(runtime_repo, tmp_path, api_environment):
    gate = threading.Event()

    class WaitingModel(FakeLLM):
        def chat(self, system, user):
            gate.wait(20)
            return super().chat(system, user)

    app = create_app(database_url=sqlite_url(tmp_path / "capacity.db"), capacity=1,
                     llm_factory=lambda _: WaitingModel(demo_responses()))
    with TestClient(app) as client:
        try:
            response = client.post("/api/tasks", json=payload(runtime_repo))
            assert response.status_code == 202
            assert client.post("/api/tasks", json=payload(tmp_path)).status_code == 429
        finally:
            gate.set()


def test_local_queue_deduplicates_and_applies_backpressure():
    async def exercise():
        queue = LocalTaskQueue(1)
        await queue.start()
        assert await queue.enqueue("one")
        assert await queue.enqueue("one")
        assert not await queue.enqueue("two")
        assert await queue.receive() == "one"
        await queue.ack("one")
        assert await queue.enqueue("two")
        assert await queue.receive() == "two"
        await queue.ack("two")
        await queue.close()
    asyncio.run(exercise())


def test_second_coordinator_is_rejected(tmp_path):
    from repopilot.database.coordinator import CoordinatorLock
    database = Database(sqlite_url(tmp_path / "single.db"))
    first, second = CoordinatorLock(database), CoordinatorLock(database)
    first.acquire()
    try:
        with pytest.raises(ValueError, match="coordinator"):
            second.acquire()
    finally:
        first.close()
    second.acquire()
    second.close()
