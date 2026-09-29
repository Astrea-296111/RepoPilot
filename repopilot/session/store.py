"""One atomic JSON file per task; no credentials or model API keys persisted."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from repopilot.agent.state import AgentState


class SessionStore:
    def __init__(self, repo: Path):
        root = repo.resolve()
        self.directory = root / ".repopilot" / "sessions"
        if not self.directory.resolve().is_relative_to(root):
            raise ValueError("会话目录指向仓库外部，已拒绝写入")
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        if not session_id or any(c not in "0123456789abcdef" for c in session_id) or len(session_id) != 32:
            raise ValueError("无效 session ID")
        return self.directory / (session_id + ".json")

    def save(self, state: AgentState) -> None:
        target = self.path(state.id)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as handle:
            json.dump(state.model_dump(), handle, ensure_ascii=False, indent=2)
            temporary = handle.name
        os.replace(temporary, target)

    def load(self, session_id: str) -> AgentState:
        return AgentState.model_validate_json(self.path(session_id).read_text(encoding="utf-8"))

    def list(self) -> list[AgentState]:
        results = []
        for path in sorted(self.directory.glob("*.json"), reverse=True):
            try: results.append(AgentState.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, OSError): continue
        return results
