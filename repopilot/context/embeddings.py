"""Real embedding provider contract; no pseudo-semantic hash fallback."""
from __future__ import annotations

import logging
import math
from typing import Protocol

import httpx

log = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    cache_key: str
    total_tokens: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddings:
    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 60,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not model or not api_key:
            raise ValueError("Embedding model and API key are required for vector retrieval")
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.timeout, self.transport = timeout, transport
        self.cache_key = f"openai-compatible:{self.base_url}:{model}"
        self.total_tokens = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                for start in range(0, len(texts), 32):
                    batch = texts[start:start + 32]
                    response = client.post(self.base_url + "/embeddings",
                        headers={"Authorization": "Bearer " + self.api_key},
                        json={"model": self.model, "input": batch, "encoding_format": "float"})
                    response.raise_for_status()
                    payload = response.json()
                    data = sorted(payload["data"], key=lambda row: row["index"])
                    if [row["index"] for row in data] != list(range(len(batch))):
                        raise ValueError("Embedding response indices do not match input")
                    for row in data:
                        vector = [float(value) for value in row["embedding"]]
                        if not vector or not all(math.isfinite(value) for value in vector):
                            raise ValueError("Empty or non-finite embedding")
                        vectors.append(vector)
                    self.total_tokens += int(payload.get("usage", {}).get("total_tokens", 0))
            if vectors and len({len(vector) for vector in vectors}) != 1:
                raise ValueError("Embedding dimension changed within batch")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("embedding request failed: %s", type(exc).__name__)
            raise ValueError("Embedding request failed; check endpoint, model and response format") from exc
        log.info("embedded chunks=%s tokens=%s", len(vectors), self.total_tokens)
        return vectors
