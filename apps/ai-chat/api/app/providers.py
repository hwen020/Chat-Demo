import asyncio
import json
import re
from dataclasses import dataclass
from typing import AsyncIterator, Protocol, Sequence

import httpx


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


class ModelProvider(Protocol):
    def events(self, history: Sequence[dict[str, str]], model: str,
               output_limit: int) -> AsyncIterator[str | Usage]:
        """Yield reply fragments and optional provider-reported usage."""


class ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def classify_status(status):
    if status == 429:
        return "provider_rate_limited"
    if status in {401, 403}:
        return "provider_credentials"
    if status in {408, 504}:
        return "generation_timeout"
    return "generation_failed"


class MockProvider:
    def stream(self, history):
        latest = history[-1]["content"]
        turn = sum(message["role"] == "user" for message in history)
        excerpt = " ".join(latest.split())[:220]
        output = (
            f'Mock reply for turn {turn}: I received "{excerpt}".\n\n'
            "A practical next step is to identify the goal, list the available inputs, "
            "and choose one small action you can verify. Tell me which part to explore next."
        )
        words = re.findall(r"\S+\s*|\s+", output)
        for start in range(0, len(words), 3):
            yield "".join(words[start:start + 3])

    async def events(self, history, model, output_limit):
        for delta in self.stream(history):
            await asyncio.sleep(0.11)
            yield delta


class OpenAIProvider:
    def __init__(self, key, transport=None):
        self.key = key
        self.transport = transport

    async def events(self, history, model, output_limit) -> AsyncIterator[str | Usage]:
        timeout = httpx.Timeout(20, connect=5)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport, trust_env=False) as client:
            async with client.stream(
                "POST", "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + self.key},
                json={
                    "model": model,
                    "messages": history,
                    "max_completion_tokens": output_limit,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "store": False,
                },
            ) as response:
                if not response.is_success:
                    raise ProviderError(classify_status(response.status_code))
                has_content = False
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        if not has_content:
                            raise ProviderError("provider_empty_reply")
                        return
                    chunk = json.loads(payload)
                    if chunk.get("error"):
                        raise ProviderError("generation_failed")
                    usage = chunk.get("usage")
                    if usage:
                        yield Usage(usage["prompt_tokens"], usage["completion_tokens"])
                    for choice in chunk.get("choices", []):
                        if choice.get("finish_reason") == "content_filter":
                            raise ProviderError("provider_filtered")
                        delta = choice.get("delta") or {}
                        text = delta.get("content") or delta.get("refusal")
                        if text:
                            has_content = True
                            yield text
                raise ProviderError("provider_stream_incomplete")
