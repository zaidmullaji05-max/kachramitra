"""
LLM providers behind one tiny interface.

Groq and Gemini both expose an OpenAI-compatible /chat/completions endpoint, so one
client implementation covers both — only base_url/model/key differ. Swapping providers
is a config change, and `FakeProvider` (no key) is skipped entirely so the API still
answers from the rule templates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import Settings

log = logging.getLogger("waste.llm")


class LLMError(RuntimeError):
    """Upstream LLM failed (timeout, 429, bad key). Callers must degrade gracefully."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, as returned by the provider


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> LLMReply: ...


class OpenAICompatProvider:
    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> LLMReply:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                )
        except httpx.HTTPError as e:
            raise LLMError(f"{self.name}: network error: {e}") from e

        if r.status_code >= 400:
            raise LLMError(f"{self.name}: HTTP {r.status_code}: {r.text[:300]}")

        data = r.json()
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"{self.name}: unexpected response shape") from e

        calls = [
            ToolCall(
                id=c.get("id", f"call_{i}"),
                name=(c.get("function") or {}).get("name", ""),
                arguments=(c.get("function") or {}).get("arguments", "{}"),
            )
            for i, c in enumerate(msg.get("tool_calls") or [])
        ]
        return LLMReply(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            model=data.get("model", self.model),
            usage=data.get("usage") or {},
        )


class GroqProvider(OpenAICompatProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile", timeout: float = 20.0):
        super().__init__("https://api.groq.com/openai/v1", api_key, model, timeout)


class GeminiProvider(OpenAICompatProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", timeout: float = 20.0):
        super().__init__("https://generativelanguage.googleapis.com/v1beta/openai", api_key, model, timeout)


def get_provider(settings: Settings) -> LLMProvider | None:
    """None means 'no LLM configured' — the caller serves rule-based answers instead."""
    choice = (settings.llm_provider or "fake").lower()
    if choice == "groq" and settings.groq_api_key:
        return GroqProvider(settings.groq_api_key, settings.llm_model or "llama-3.3-70b-versatile",
                            settings.llm_timeout_s)
    if choice == "gemini" and settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key, settings.llm_model or "gemini-2.5-flash",
                              settings.llm_timeout_s)
    if choice not in ("fake", "groq", "gemini"):
        log.warning("unknown LLM_PROVIDER=%r, falling back to rules", choice)
    return None
