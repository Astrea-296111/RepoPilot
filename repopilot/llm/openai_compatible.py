"""Synchronous OpenAI-compatible chat completions adapter."""
import json
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
        request = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.settings.llm_reasoning_effort:
            request["reasoning_effort"] = self.settings.llm_reasoning_effort
        if self.settings.llm_max_output_tokens is not None:
            request["max_tokens"] = self.settings.llm_max_output_tokens
        if self.settings.llm_stream:
            request.update(stream=True, stream_options={"include_usage": True})
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                if self.settings.llm_stream:
                    with client.stream("POST", url, headers={"Authorization": f"Bearer {self.settings.llm_api_key}"}, json=request) as response:
                        response.raise_for_status()
                        content_parts = []
                        usage = {}
                        for line in response.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            if not data:
                                continue
                            chunk = json.loads(data)
                            if chunk.get("error"):
                                raise RuntimeError(f"模型服务流式响应错误: {chunk['error']}")
                            if chunk.get("usage"):
                                usage = chunk["usage"]
                            for choice in chunk.get("choices") or []:
                                content_parts.append((choice.get("delta") or {}).get("content") or "")
                        content = "".join(content_parts)
                        if not content:
                            raise RuntimeError("模型服务流式响应缺少正文")
                else:
                    response = client.post(url, headers={"Authorization": f"Bearer {self.settings.llm_api_key}"}, json=request)
                    response.raise_for_status()
                    payload = response.json()
                    content = payload["choices"][0]["message"]["content"]
                    usage = payload.get("usage") or {}
            logging.getLogger(__name__).info("LLM latency=%.2fs", time.monotonic() - started)
            return LLMResponse(
                content,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"模型服务请求超时（{self.settings.llm_timeout_seconds:g} 秒，{type(exc).__name__}，已等待 {time.monotonic() - started:.1f} 秒）") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"模型服务返回 HTTP {exc.response.status_code}；请检查 Base URL、Key 和模型名") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise RuntimeError("模型服务连接或响应失败；检查网络、接口格式和超时设置") from exc
