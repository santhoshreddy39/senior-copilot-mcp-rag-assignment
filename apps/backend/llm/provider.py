"""
Pluggable LLM provider abstraction.

The copilot's answer-synthesis step (apps/backend/copilot/orchestrator.py)
depends only on the ``LLMProvider`` protocol below, never on a specific
vendor SDK, so switching model vendors is a config change, not a code change.
Four implementations are provided:

  * OpenAIProvider       — set LLM_PROVIDER=openai,     OPENAI_API_KEY
  * AnthropicProvider    — set LLM_PROVIDER=anthropic,  ANTHROPIC_API_KEY
  * AzureOpenAIProvider  — set LLM_PROVIDER=azure_openai, AZURE_OPENAI_* vars
  * TemplateProvider     — no key required; deterministic, offline, used
                            automatically when no provider is configured so
                            the app is usable straight out of the box
                            (``docker compose up`` with an empty .env still
                            produces a grounded, cited answer).

get_llm_provider() reads LLM_PROVIDER from the environment and returns the
matching implementation, falling back to TemplateProvider on missing
configuration rather than crashing the request.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger("llm_provider")


class LLMProvider(Protocol):
    name: str

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 700) -> str:
        """Returns a plain-text completion. Implementations must not raise on
        provider-side failure — they should log and let the caller fall back."""
        ...


class TemplateProvider:
    """
    Deterministic, offline fallback. Does not call any external service. Used
    automatically when no LLM_PROVIDER/API key is configured, and as the
    final fallback if a configured provider call fails at request time — so a
    missing/expired key degrades the answer's fluency, not its availability.
    """

    name = "template"

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 700) -> str:
        return ""  # signals "no LLM available"; the caller uses its own template synthesis


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI  # imported lazily so the dependency is optional

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 700) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("OpenAI completion failed; falling back to template synthesis")
            return ""


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        import anthropic  # imported lazily

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 700) -> str:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        except Exception:
            logger.exception("Anthropic completion failed; falling back to template synthesis")
            return ""


class AzureOpenAIProvider:
    name = "azure_openai"

    def __init__(self, api_key: str, endpoint: str, deployment: str, api_version: str = "2024-06-01"):
        from openai import AsyncAzureOpenAI  # imported lazily

        self._client = AsyncAzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version)
        self._deployment = deployment

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 700) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("Azure OpenAI completion failed; falling back to template synthesis")
            return ""


def get_llm_provider() -> LLMProvider:
    provider_name = os.environ.get("LLM_PROVIDER", "").strip().lower()
    try:
        if provider_name == "openai":
            api_key = os.environ["OPENAI_API_KEY"]
            return OpenAIProvider(api_key=api_key, model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        if provider_name == "anthropic":
            api_key = os.environ["ANTHROPIC_API_KEY"]
            return AnthropicProvider(
                api_key=api_key, model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
            )
        if provider_name == "azure_openai":
            return AzureOpenAIProvider(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            )
    except KeyError as missing:
        logger.warning(
            "LLM_PROVIDER=%s configured but %s is not set; using offline TemplateProvider", provider_name, missing
        )
    except ImportError:
        logger.warning(
            "LLM_PROVIDER=%s configured but its SDK is not installed; using offline TemplateProvider", provider_name
        )
    return TemplateProvider()
