"""Async workers execute synchronous agents outside FastAPI's event loop."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging

from repopilot.agent.state import AgentState
from repopilot.database.coordinator import CoordinatorLock
from repopilot.database.store import Database
from .queue import TaskQueue

log = logging.getLogger(__name__)


class TaskService:
    def __init__(self, database: Database, queue: TaskQueue,
                 runner: Callable[[dict, AgentState], None], workers: int = 2, capacity: int = 100) -> None:
        self.database, self.queue, self.runner = database, queue, runner
        self.workers, self.capacity = workers, capacity
        self.lock = CoordinatorLock(database)
        self.stopping = False
        self._workers: list[asyncio.Task] = []
        self._dispatcher: asyncio.Task | None = None
        self._submission_lock = asyncio.Lock()

    async def start(self) -> None:
        await asyncio.to_thread(self.lock.acquire)
        try:
            await self.queue.start()
            for state in await asyncio.to_thread(self.database.list, statuses={"running"}):
                state.error = "interrupted_by_restart"
                state.finish("interrupted", "Process stopped during execution; inspect the workspace before resuming")
                await asyncio.to_thread(self.database.save, state)
            self._workers = [asyncio.create_task(self._worker(), name=f"repopilot-worker-{i}") for i in range(self.workers)]
            self._dispatcher = asyncio.create_task(self._dispatch(), name="repopilot-outbox")
        except Exception:
            await self.queue.close()
            await asyncio.to_thread(self.lock.close)
            raise

    async def submit(self, request: dict, state: AgentState) -> None:
        async with self._submission_lock:
            pending = await asyncio.to_thread(self.database.list, statuses={"pending", "running"})
            if self.stopping or len(pending) >= self.capacity:
                raise OverflowError("Task capacity reached; retry later")
            await asyncio.to_thread(self.database.create_task, state, request)
        # The committed pending row is an outbox entry. Queue outages do not lose
        # accepted work: dispatcher retries transport, and worker claims once.
        try:
            await self.queue.enqueue(state.id)
        except Exception:
            log.warning("task=%s persisted; queue delivery deferred", state.id)

    async def _dispatch(self) -> None:
        while not self.stopping:
            try:
                for state in await asyncio.to_thread(self.database.list, statuses={"pending"}):
                    if not await self.queue.enqueue(state.id):
                        break
            except Exception:
                log.exception("task outbox dispatch failed; will retry")
            await asyncio.sleep(0.5)

    async def _worker(self) -> None:
        while not self.stopping:
            task_id = None
            try:
                task_id = await self.queue.receive()
                if task_id is None:
                    continue
                if not await asyncio.to_thread(self.database.claim, task_id):
                    continue
                state = await asyncio.to_thread(self.database.load, task_id)
                request = await asyncio.to_thread(self.database.request, task_id)
                try:
                    await asyncio.to_thread(self.runner, request, state)
                except Exception as exc:
                    state.error = f"{type(exc).__name__}: {exc}"
                    state.finish("failed", "Task execution failed")
                    await asyncio.to_thread(self.database.save, state)
                    log.exception("task=%s execution failed", task_id)
            except Exception:
                log.exception("task queue worker failed; will retry transport")
                await asyncio.sleep(1)
            finally:
                if task_id:
                    try:
                        await self.queue.ack(task_id)
                    except Exception:
                        log.exception("task=%s queue acknowledgement failed", task_id)

    async def close(self) -> None:
        self.stopping = True
        if self._dispatcher:
            self._dispatcher.cancel()
            await asyncio.gather(self._dispatcher, return_exceptions=True)
        # A thread cannot safely be force-cancelled while it modifies a repo.
        # Graceful shutdown waits for current agents; queued SQL rows survive.
        await asyncio.gather(*self._workers, return_exceptions=True)
        await self.queue.close()
        await asyncio.to_thread(self.lock.close)
