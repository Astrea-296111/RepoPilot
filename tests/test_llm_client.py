"""Check the wire format used by the paid benchmark without calling an API."""
import json

import httpx
import pytest

from repopilot.config import Settings
from repopilot.llm import openai_compatible


def test_streaming_chat_reassembles_text_and_usage(monkeypatch):
    captured = {}

    def respond(request):
        captured.update(json.loads(request.content))
        body = (
            'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"{\\"patches\\":"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"[]}"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":7}}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client_type = httpx.Client
    monkeypatch.setattr(openai_compatible.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond)))
    llm = openai_compatible.OpenAICompatibleLLM(Settings(llm_api_key="example", llm_model="qwen3.8-max", llm_stream=True, llm_reasoning_effort="medium", llm_max_output_tokens=4096))
    result = llm.chat("system", "user")
    assert result.content == '{"patches":[]}'
    assert (result.prompt_tokens, result.completion_tokens) == (12, 7)
    assert captured["reasoning_effort"] == "medium"
    assert captured["max_tokens"] == 4096
    assert captured["stream_options"] == {"include_usage": True}
    assert captured["messages"][1]["content"] == "user"


def test_stream_timeout_identifies_read_timeout(monkeypatch):
    def respond(request):
        raise httpx.ReadTimeout("request timed out", request=request)

    client_type = httpx.Client
    monkeypatch.setattr(openai_compatible.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond)))
    llm = openai_compatible.OpenAICompatibleLLM(Settings(llm_api_key="example", llm_model="qwen3.8-max", llm_stream=True, llm_timeout_seconds=180))
    with pytest.raises(RuntimeError, match="模型服务请求超时.*ReadTimeout.*已等待"):
        llm.chat("system", "user")
