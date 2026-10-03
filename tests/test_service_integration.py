"""Real Redis/PostgreSQL tests enabled by CI service containers or local endpoints."""
import asyncio
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from repopilot.agent.agent import demo_responses
from repopilot.api.server import create_app
from repopilot.api.queue import RedisTaskQueue
from repopilot.llm.base import FakeLLM


@pytest.mark.skipif(not os.getenv("REPOPILOT_TEST_REDIS_URL"), reason="requires real Redis")
def test_real_redis_reliable_queue():
    async def exercise():
        queue = RedisTaskQueue(os.environ["REPOPILOT_TEST_REDIS_URL"], capacity=1, prefix="test-" + uuid4().hex)
        try:
            await queue.start()
            assert await queue.enqueue("one")
            assert await queue.enqueue("one")
            assert not await queue.enqueue("two")
            assert await queue.receive() == "one"
            assert await queue.redis.llen(queue.processing) == 1
            await queue.ack("one")
            assert await queue.redis.llen(queue.processing) == 0
        finally:
            await queue.redis.delete(queue.ready, queue.processing, queue.known)
            await queue.close()
    asyncio.run(exercise())


@pytest.mark.skipif(not os.getenv("REPOPILOT_TEST_REDIS_URL"), reason="requires real Redis")
def test_real_redis_recovers_receive_response_loss(monkeypatch):
    """Move in real Redis, then lose the reply; a pending outbox offer repairs it."""
    async def exercise():
        queue = RedisTaskQueue(os.environ["REPOPILOT_TEST_REDIS_URL"], capacity=1, prefix="test-" + uuid4().hex)
        try:
            await queue.start()
            original = queue.redis.brpoplpush

            async def lose_reply(*args, **kwargs):
                assert await original(*args, **kwargs) == "lost"
                raise ConnectionError("receive response lost after server-side move")

            assert await queue.enqueue("lost")
            monkeypatch.setattr(queue.redis, "brpoplpush", lose_reply)
            with pytest.raises(ConnectionError):
                await queue.receive()
            assert await queue.redis.lrange(queue.processing, 0, -1) == ["lost"]
            # A full ready queue must not remove the recoverable processing item.
            assert await queue.enqueue("other")
            assert not await queue.enqueue("lost")
            assert await queue.redis.lrange(queue.processing, 0, -1) == ["lost"]
            monkeypatch.setattr(queue.redis, "brpoplpush", original)
            assert await queue.receive() == "other"
            await queue.ack("other")
            assert await queue.enqueue("lost")
            assert await queue.enqueue("lost")
            assert await queue.redis.llen(queue.ready) == 1
            assert await queue.redis.llen(queue.processing) == 0
            assert await queue.receive() == "lost"
            await queue.ack("lost")
            await queue.ack("lost")  # Repeating an ambiguous ACK is safe.
            assert await queue.redis.scard(queue.known) == 0
            assert await queue.redis.llen(queue.processing) == 0
        finally:
            await queue.redis.delete(queue.ready, queue.processing, queue.known)
            await queue.close()
    asyncio.run(exercise())


@pytest.mark.skipif(not all(os.getenv(key) for key in ("REPOPILOT_TEST_REDIS_URL", "REPOPILOT_TEST_DATABASE_URL")),
                    reason="requires real PostgreSQL and Redis")
def test_postgres_redis_api_end_to_end(runtime_repo, monkeypatch):
    from test_api_tasks import payload, wait_done
    monkeypatch.setenv("REPOPILOT_API_ROOT", str(runtime_repo.parent))
    monkeypatch.setenv("REPOPILOT_API_ALLOW_LOCAL", "1")
    url, redis = os.environ["REPOPILOT_TEST_DATABASE_URL"], os.environ["REPOPILOT_TEST_REDIS_URL"]
    app = create_app(database_url=url, redis_url=redis, llm_factory=lambda _: FakeLLM(demo_responses()))
    with TestClient(app) as client:
        response = client.post("/api/tasks", json=payload(runtime_repo, runtime="langgraph", tool_backend="mcp",
                                                       retrieval="hybrid", memory=True))
        assert response.status_code == 202, response.text
        task_id = response.json()["task_id"]
        result = wait_done(client, task_id)
        assert result["status"] == "completed", result
        assert "event: end" in client.get(f"/api/tasks/{task_id}/stream").text
    with TestClient(create_app(database_url=url, redis_url=redis, llm_factory=lambda _: FakeLLM([]))) as client:
        assert client.get(f"/api/tasks/{task_id}").json()["status"] == "completed"
