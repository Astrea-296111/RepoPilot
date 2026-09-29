"""Small evaluation-only retry wrapper for transport/rate-limit failures."""
from __future__ import annotations

import time


class RetryingLLM:
    def __init__(self, inner, max_attempts: int = 3):
        self.inner = inner
        self.max_attempts = max_attempts
        self.retries = 0

    @staticmethod
    def _retryable(exc: RuntimeError) -> bool:
        message = str(exc)
        if "连接或响应失败" in message:
            return True
        return any(f"HTTP {code}" in message for code in (429, 500, 502, 503, 504))

    def chat(self, system: str, user: str):
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.inner.chat(system, user)
            except RuntimeError as exc:
                if attempt >= self.max_attempts or not self._retryable(exc):
                    raise
                self.retries += 1
                time.sleep(min(2 ** (attempt - 1), 4))
        raise AssertionError("unreachable")
