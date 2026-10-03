"""SQLite FTS5 repair memory, isolated by repository and verified outcome."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from typing import Iterator

from repopilot.agent.state import AgentState
from repopilot.context.chunks import tokenize

log = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, repo: Path, path: Path | None = None) -> None:
        self.repo = str(repo.resolve())
        self.path = path or repo.resolve() / ".repopilot" / "memory.db"
        if path is None and not self.path.resolve().is_relative_to(repo.resolve()):
            raise ValueError("Memory path escapes repository")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL UNIQUE, repo TEXT NOT NULL,
                task TEXT NOT NULL, solution TEXT NOT NULL, error TEXT NOT NULL, fix TEXT NOT NULL,
                verified INTEGER NOT NULL, created_at REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS memory_repo_verified ON experiences(repo, verified)")
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS experience_search USING fts5(task, solution, error, fix)")
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
                log.warning("SQLite FTS5 unavailable; memory uses bounded lexical fallback")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def remember(self, state: AgentState) -> None:
        if state.status not in {"completed", "failed"}:
            return
        if str(Path(state.repo_path).resolve()) != self.repo:
            raise ValueError("Memory repository mismatch")
        verified = int(state.status == "completed" and state.test_status == "passed")
        errors = "\n".join(item["output"][-1000:] for item in state.tool_history if not item["ok"])[-3000:]
        values = (state.id, self.repo, state.task[:4000], state.summary[:4000],
                  state.error[:1000] or errors, state.final_diff[:8000], verified, time.time())
        with self._connect() as db:
            db.execute("""INSERT INTO experiences(session_id,repo,task,solution,error,fix,verified,created_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                solution=excluded.solution,error=excluded.error,fix=excluded.fix,
                verified=excluded.verified,created_at=excluded.created_at""", values)
            row_id = db.execute("SELECT id FROM experiences WHERE session_id=?", (state.id,)).fetchone()[0]
            if self.fts:
                db.execute("DELETE FROM experience_search WHERE rowid=?", (row_id,))
                db.execute("INSERT INTO experience_search(rowid,task,solution,error,fix) VALUES(?,?,?,?,?)",
                           (row_id, *(" ".join(tokenize(value)) for value in values[2:6])))
        log.info("memory recorded session=%s verified=%s", state.id, bool(verified))

    def search(self, task: str, limit: int = 3) -> list[dict]:
        terms = sorted(set(tokenize(task)))[:32]
        if not terms or limit <= 0:
            return []
        with self._connect() as db:
            if self.fts:
                query = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
                rows = db.execute("""SELECT e.*, bm25(experience_search) AS rank
                    FROM experience_search JOIN experiences e ON e.id=experience_search.rowid
                    WHERE experience_search MATCH ? AND e.repo=? AND e.verified=1
                    ORDER BY rank, e.created_at DESC LIMIT ?""", (query, self.repo, min(limit, 10))).fetchall()
            else:
                candidates = db.execute("SELECT * FROM experiences WHERE repo=? AND verified=1 ORDER BY created_at DESC LIMIT 200",
                                        (self.repo,)).fetchall()
                rows = sorted((row for row in candidates if set(terms).intersection(tokenize(row["task"]))),
                              key=lambda row: -len(set(terms).intersection(tokenize(row["task"]))))[:min(limit, 10)]
        return [{"session_id": row["session_id"], "task": row["task"], "solution": row["solution"],
                 "error": row["error"], "fix": row["fix"], "verified": True} for row in rows]
