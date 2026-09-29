"""Synchronous OpenAI-compatible chat completions adapter."""
import time
import logging
import httpx
from .base import LLMResponse
from repopilot.config import Settings


class OpenAICompatibleLLM:
    def __init__(self, settings: Settings):
        if not settings.llm_api_key or not settings.llm_model:
            raise ValueError("请在 .env 中设置 LLM_API_KEY 和 LLM_MODEL；无密钥体验用 --fake-demo")
        self.settings = settings

    def chat(self, system: str, user: str) -> LLMResponse:
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        started = time.monotonic()
        try:
            with httpx.Client(timeout=90) as client:
                response = client.post(url, headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                    json={"model": self.settings.llm_model, "temperature": 0,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
                response.raise_for_status()
                payload = response.json()
            usage = payload.get("usage") or {}
            logging.getLogger(__name__).info("LLM latency=%.2fs", time.monotonic()-started)
            return LLMResponse(payload["choices"][0]["message"]["content"],
                               usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"模型服务返回 HTTP {exc.response.status_code}；请检查 Base URL、Key 和模型名") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise RuntimeError("模型服务连接或响应失败；检查网络、接口格式和超时设置") from exc
