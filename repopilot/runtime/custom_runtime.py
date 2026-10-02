"""Explicit adapter for the original, framework-free Agent Loop."""
from __future__ import annotations

from typing import TYPE_CHECKING

from repopilot.agent.state import AgentState

if TYPE_CHECKING:
    from repopilot.agent.agent import RepoPilot


class CustomRuntime:
    def __init__(self, owner: RepoPilot) -> None:
        self.owner = owner

    def run(self, state: AgentState) -> AgentState:
        return self.owner._run_custom(state)
