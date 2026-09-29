"""The tiny model interface used by the planner and agent."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLM(Protocol):
    def chat(self, system: str, user: str) -> LLMResponse: ...


class FakeLLM:
    """Deterministic scripted model for tests and the key-free demo."""
    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    def chat(self, system: str, user: str) -> LLMResponse:
        if not self.responses:
            raise RuntimeError("FakeLLM script exhausted")
        return LLMResponse(self.responses.pop(0))

