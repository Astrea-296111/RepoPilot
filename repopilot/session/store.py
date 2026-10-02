"""Database-backed sessions with read-once import of legacy JSON transcripts."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from repopilot.agent.state import AgentState
from repopilot.database.store import Database, sqlite_url

log = logging.getLogger(__name__)


class SessionStore:
    def __init__(self, repo: Path, database: Database | None = None) -> None:
        self.root = repo.resolve()
        self.directory = self.root / ".repopilot" / "sessions"
        db_path = self.root / ".repopilot" / "repopilot.db"
        if not self.directory.resolve().is_relative_to(self.root) or not db_path.resolve().is_relative_to(self.root):
            raise ValueError("会话目录指向仓库外部，已拒绝写入")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = database or Database(os.getenv("REPOPILOT_DATABASE_URL") or sqlite_url(db_path))

    def path(self, session_id: str) -> Path:
        """Legacy path only. New saves go into the database."""
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            raise ValueError("无效 session ID")
        path = self.directory / (session_id + ".json")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("会话文件指向仓库外部")
        return path

    def save(self, state: AgentState) -> None:
        self.path(state.id)
        if Path(state.repo_path).resolve() != self.root:
            raise ValueError("会话仓库不一致")
        self.database.save(state)

    def load(self, session_id: str) -> AgentState:
        legacy = self.path(session_id)
        try:
            state = self.database.load(session_id)
        except FileNotFoundError:
            state = AgentState.model_validate_json(legacy.read_text(encoding="utf-8"))
            if state.id != session_id:
                raise ValueError("JSON 会话 ID 与文件名不一致")
            self.save(state)
            log.info("imported legacy session=%s", session_id)
        if Path(state.repo_path).resolve() != self.root:
            raise ValueError("会话仓库不一致")
        return state

    def list(self) -> list[AgentState]:
        for path in self.directory.glob("*.json"):
            try:
                self.load(path.stem)
            except (ValueError, OSError):
                log.warning("skipping invalid legacy session: %s", path.name)
        return self.database.list(repo=str(self.root))
