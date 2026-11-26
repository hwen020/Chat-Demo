import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from app import model_config
from app.providers import OpenAIProvider, ProviderError, Usage


def test_openai_stream_sends_context_and_captures_usage():
    messages = [
        {"role": "user", "content": "First synthetic prompt"},
        {"role": "assistant", "content": "First synthetic answer"},
        {"role": "user", "content": "Follow-up"},
    ]

    def upstream(request):
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-only-key"
        assert json.loads(request.content) == {
            "model": "configured-test-model", "messages": messages, "max_completion_tokens": 128,
            "stream": True, "stream_options": {"include_usage": True}, "store": False,
        }
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":22,"completion_tokens":3}}\n\n'
            'data: [DONE]\n\n'
        ))

    async def collect():
        provider = OpenAIProvider("test-only-key", transport=httpx.MockTransport(upstream))
        return [part async for part in provider.events(messages, "configured-test-model", 128)]

    assert asyncio.run(collect()) == ["Hello", " world", Usage(22, 3)]


def test_interrupted_provider_stream_fails():
    async def collect():
        transport = httpx.MockTransport(lambda _: httpx.Response(200, text='data: {"choices":[]}\n\n'))
        provider = OpenAIProvider("test-only-key", transport=transport)
        return [part async for part in provider.events([], "configured-test-model", 128)]

    with pytest.raises(ProviderError, match="provider_stream_incomplete"):
        asyncio.run(collect())


def test_context_keeps_recent_complete_turns(monkeypatch):
    monkeypatch.setattr(model_config, "INPUT_LIMIT", 96)
    turns = [
        {"seq": 1, "role": "user", "content": "a" * 100},
        {"seq": 2, "role": "assistant", "content": "first"},
        {"seq": 3, "role": "user", "content": "again"},
    ]
    assert model_config.context_window(turns) == (3, 57)
    with pytest.raises(HTTPException) as error:
        model_config.context_window(turns[:1])
    assert error.value.detail == "input_token_limit"
