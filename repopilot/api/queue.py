"""Bounded local queue or Redis reliable-list transport; SQL is the durable outbox."""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

log = logging.getLogger(__name__)


class TaskQueue(Protocol):
    async def start(self) -> None: ...
    async def enqueue(self, task_id: str) -> bool: ...
    async def receive(self) -> str | None: ...
    async def ack(self, task_id: str) -> None: ...
    async def close(self) -> None: ...


class LocalTaskQueue:
    def __init__(self, capacity: int = 100) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=capacity)
        self.known: set[str] = set()

    async def start(self) -> None:
        pass

    async def enqueue(self, task_id: str) -> bool:
        if task_id in self.known:
            return True
        try:
            self.queue.put_nowait(task_id)
        except asyncio.QueueFull:
            return False
        self.known.add(task_id)
        return True

    async def receive(self) -> str | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=1)
        except asyncio.TimeoutError:
            return None

    async def ack(self, task_id: str) -> None:
        self.known.discard(task_id)
        self.queue.task_done()

    async def close(self) -> None:
        pass


class RedisTaskQueue:
    def __init__(self, url: str, capacity: int = 100, prefix: str = "repopilot") -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise ValueError("Redis queue requires: pip install -e '.[server]'") from exc
        self.redis = Redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
        self.capacity = capacity
        self.ready, self.processing, self.known = (prefix + suffix for suffix in (":ready", ":processing", ":known"))

    async def start(self) -> None:
        await self.redis.ping()
        # One DB coordinator owns this namespace. SQL pending tasks refill it;
        # previous running tasks become interrupted and are never auto-replayed.
        await self.redis.delete(self.ready, self.processing, self.known)
        log.info("redis task transport ready")

    async def enqueue(self, task_id: str) -> bool:
        """Offer a SQL-pending ID, including recovery of a lost receive response.

        A stale outbox read may redeliver an already claimed ID. The SQL claim
        is the execution gate; queue deduplication alone is never authorization.
        """
        script = """
        if redis.call('LPOS', KEYS[1], ARGV[1]) then return 1 end
        if redis.call('LLEN', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
        redis.call('LREM', KEYS[3], 0, ARGV[1])
        redis.call('SADD', KEYS[2], ARGV[1])
        redis.call('LPUSH', KEYS[1], ARGV[1])
        return 1
        """
        return bool(await self.redis.eval(script, 3, self.ready, self.known, self.processing, task_id, self.capacity))

    async def receive(self) -> str | None:
        return await self.redis.brpoplpush(self.ready, self.processing, timeout=1)

    async def ack(self, task_id: str) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing, 0, task_id)
            pipe.srem(self.known, task_id)
            await pipe.execute()

    async def close(self) -> None:
        await self.redis.aclose()
