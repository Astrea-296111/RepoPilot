"""Single API coordinator lock; multiple internal task workers remain supported."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from .store import Database


class CoordinatorLock:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.handle: Any = None
        self.connection: Any = None

    def acquire(self) -> None:
        engine = self.database.engine
        if engine.dialect.name == "postgresql":
            self.connection = engine.connect()
            locked = self.connection.execute(text("SELECT pg_try_advisory_lock(728194083)" )).scalar()
            if not locked:
                self.close()
                raise ValueError("Another RepoPilot API coordinator owns this database; use one Uvicorn worker")
        elif engine.dialect.name == "sqlite" and engine.url.database not in {None, ":memory:"}:
            self.handle = Path(engine.url.database + ".lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    self.handle.write(b"0")
                    self.handle.flush()
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self.close()
                raise ValueError("Another RepoPilot API coordinator owns this database") from exc

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.execute(text("SELECT pg_advisory_unlock(728194083)"))
                self.connection.commit()
            finally:
                self.connection.close()
                self.connection = None
        if self.handle is not None:
            self.handle.close()
            self.handle = None
