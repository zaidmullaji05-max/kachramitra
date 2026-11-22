
"""
LLM providers behind one tiny interface.

Supports Groq and Gemini through OpenAI-compatible chat completions.
Gemini retries temporary service errors before falling back to rules.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .config import Settings

log = logging.getLogger("waste.llm")


class LLMError(RuntimeError):
    """Upstream LLM failed."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


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
    ) -> LLMReply:
        ...


class OpenAICompatProvider:
    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
    ):
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
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )

        except httpx.HTTPError as error:
            raise LLMError(
                f"{self.name}: network error: {error}"
            ) from error

        if response.status_code >= 400:
            raise LLMError(
                f"{self.name}: HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as error:
            raise LLMError(
                f"{self.name}: unexpected response format"
            ) from error

        calls = [
            ToolCall(
                id=call.get("id", f"call_{index}"),
                name=(call.get("function") or {}).get("name", ""),
                arguments=(call.get("function") or {}).get(
                    "arguments", "{}"
                ),
            )
            for index, call in enumerate(
                message.get("tool_calls") or []
            )
        ]

        return LLMReply(
            text=(message.get("content") or "").strip(),
            tool_calls=calls,
            model=data.get("model", self.model),
            usage=data.get("usage") or {},
        )


class GroqProvider(OpenAICompatProvider):
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        timeout: float = 30.0,
    ):
        super().__init__(
            "https://api.groq.com/openai/v1",
            api_key,
            model,
            timeout,
        )



class GeminiProvider(OpenAICompatProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        timeout: float = 60.0,
    ):
        super().__init__(
            "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key,
            model,
            timeout,
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 800,
    ) -> LLMReply:
        retryable_codes = ("429", "500", "502", "503", "504")

        for attempt in range(3):
            try:
                return await super().complete(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            except LLMError as error:
                error_text = str(error).lower()

                retryable = (
                    any(code in error_text for code in retryable_codes)
                    or "timeout" in error_text
                    or "timed out" in error_text
                )

                if not retryable or attempt == 2:
                    log.error("Gemini request failed: %s", error)
                    raise

                delay = 2 ** (attempt + 1)

                log.warning(
                    "Gemini temporarily unavailable. "
                    "Retrying in %s seconds.",
                    delay,
                )

                await asyncio.sleep(delay)





def get_provider(settings: Settings) -> LLMProvider | None:
    """
    Select the configured LLM provider.

    None means no LLM is configured and the application
    should use its local rule-based fallback.
    """

    choice = (settings.llm_provider or "fake").strip().lower()

    if choice == "groq" and settings.groq_api_key:
        return GroqProvider(
            settings.groq_api_key,
            settings.llm_model or "llama-3.3-70b-versatile",
            settings.llm_timeout_s,
        )

    if choice == "gemini" and settings.gemini_api_key:
        return GeminiProvider(
            settings.gemini_api_key,
            settings.llm_model or "gemini-3.8-flash",
            settings.llm_timeout_s,
        )

    if choice not in ("fake", "groq", "gemini"):
        log.warning(
            "Unknown LLM_PROVIDER=%r. Using local rules.",
            choice,
        )

    elif choice == "gemini" and not settings.gemini_api_key:
        log.error(
            "LLM_PROVIDER is gemini but GEMINI_API_KEY is missing."
        )

    elif choice == "groq" and not settings.groq_api_key:
        log.error(
            "LLM_PROVIDER is groq but GROQ_API_KEY is missing."
        )

    return None
