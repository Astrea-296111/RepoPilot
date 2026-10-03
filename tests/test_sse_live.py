"""A real HTTP stream must emit an event while the model is still blocked."""
import socket
import threading
import time

import httpx
import uvicorn

from repopilot.agent.agent import demo_responses
from repopilot.api.server import create_app
from repopilot.database.store import sqlite_url
from repopilot.llm.base import FakeLLM


def test_sse_flushes_before_agent_finishes(runtime_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("REPOPILOT_API_ROOT", str(runtime_repo.parent))
    monkeypatch.setenv("REPOPILOT_API_ALLOW_LOCAL", "1")
    gate = threading.Event()

    class WaitingLLM(FakeLLM):
        def chat(self, system, user):
            assert gate.wait(20)
            return super().chat(system, user)

    app = create_app(database_url=sqlite_url(tmp_path / "stream.db"), redis_url="",
                     llm_factory=lambda _: WaitingLLM(demo_responses()))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
            response = client.post("/api/tasks", json={"repo_path": str(runtime_repo), "task": "fix",
                                                      "executor": "local", "approval": "auto"})
            assert response.status_code == 202
            task_id = response.json()["task_id"]
            with client.stream("GET", f"/api/tasks/{task_id}/stream") as stream:
                first = next(line for line in stream.iter_lines() if line.startswith("data: "))
                assert '"status": "pending"' in first or '"status": "running"' in first
                assert not gate.is_set()  # Proves no response buffering until completion.
            gate.set()
    finally:
        gate.set()
        server.should_exit = True
        thread.join(timeout=30)
        listener.close()
    assert not thread.is_alive()
