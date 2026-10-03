"""Configuration loaded from environment and an optional .env file."""
from pathlib import Path
import os
from typing import Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Settings(BaseModel):
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=90.0, ge=5, le=600)
    llm_max_output_tokens: int | None = Field(default=None, ge=128, le=32768)
    llm_reasoning_effort: str = ""
    llm_stream: bool = False
    docker_image: str = "repopilot-sandbox:dev"
    max_steps: int = Field(default=15, ge=1, le=100)
    max_context_chars: int = Field(default=30000, ge=2000)
    reflection_enabled: bool = False
    retrieval_mode: Literal["legacy", "hybrid"] = "legacy"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = ""
    embedding_api_key: str = ""
    memory_enabled: bool = False
    otel_enabled: bool = False
    otel_exporter: str = "console"
    otel_endpoint: str = ""

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ".env", override=False)
        return cls(
            llm_base_url=os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1",
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            llm_max_output_tokens=int(os.environ["LLM_MAX_OUTPUT_TOKENS"]) if os.getenv("LLM_MAX_OUTPUT_TOKENS") else None,
            llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", ""),
            llm_stream=os.getenv("LLM_STREAM", "false").lower() in {"1", "true", "yes"},
            docker_image=os.getenv("REPOPILOT_DOCKER_IMAGE", "repopilot-sandbox:dev"),
            max_steps=int(os.getenv("REPOPILOT_MAX_STEPS", "15")),
            max_context_chars=int(os.getenv("REPOPILOT_MAX_CONTEXT_CHARS", "30000")),
            reflection_enabled=os.getenv("REPOPILOT_REFLECTION", "0").lower() in {"1", "true", "yes"},
            retrieval_mode=os.getenv("REPOPILOT_RETRIEVAL", "legacy"),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1",
            embedding_model=os.getenv("EMBEDDING_MODEL", ""),
            embedding_api_key=os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY", ""),
            memory_enabled=os.getenv("REPOPILOT_MEMORY", "0").lower() in {"1", "true", "yes"},
            otel_enabled=os.getenv("REPOPILOT_OTEL_ENABLED", "0").lower() in {"1", "true", "yes"},
            otel_exporter=os.getenv("REPOPILOT_OTEL_EXPORTER", "console"),
            otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        )
