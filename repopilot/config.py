"""Configuration loaded from environment and an optional .env file."""
from pathlib import Path
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Settings(BaseModel):
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    docker_image: str = "repopilot-sandbox:dev"
    max_steps: int = Field(default=15, ge=1, le=100)
    max_context_chars: int = Field(default=30000, ge=2000)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ".env", override=False)
        return cls(
            llm_base_url=os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1",
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            docker_image=os.getenv("REPOPILOT_DOCKER_IMAGE", "repopilot-sandbox:dev"),
            max_steps=int(os.getenv("REPOPILOT_MAX_STEPS", "15")),
            max_context_chars=int(os.getenv("REPOPILOT_MAX_CONTEXT_CHARS", "30000")),
        )
