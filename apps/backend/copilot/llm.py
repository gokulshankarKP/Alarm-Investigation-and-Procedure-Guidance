"""LLM provider abstraction.

The orchestration layer depends only on ``LLMClient.generate_json``. ``OllamaLLM`` uses
LangChain's ``ChatOllama`` (local qwen3 by default); ``NullLLM`` disables generation so the
copilot falls back to rule-based intent detection and the deterministic answer composer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Protocol

from copilot.config import CopilotSettings
from shared.observability import log_event

logger = logging.getLogger(__name__)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str
    enabled: bool

    async def generate_json(self, system: str, user: str, *, purpose: str) -> dict[str, Any]: ...


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output (tolerates think blocks and fences)."""
    cleaned = _FENCE.sub("", _THINK.sub("", text)).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("model output contains no JSON object") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"model output is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise LLMError("model output JSON is not an object")
    return value


class NullLLM:
    provider = "none"
    model = "none"
    enabled = False

    async def generate_json(self, system: str, user: str, *, purpose: str) -> dict[str, Any]:
        raise LLMError("LLM disabled (LLM_PROVIDER=none)")


class OllamaLLM:
    provider = "ollama"
    enabled = True

    def __init__(self, settings: CopilotSettings) -> None:
        from langchain_ollama import ChatOllama

        self.model = settings.ollama_model
        self._timeout = settings.llm_timeout_s
        self._chat = ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
            num_ctx=settings.llm_num_ctx,
            num_predict=settings.llm_max_tokens,
            format="json",
            reasoning=False,  # qwen3: skip the thinking phase, we need structured output
            client_kwargs={"timeout": settings.llm_timeout_s},
        )

    async def generate_json(self, system: str, user: str, *, purpose: str) -> dict[str, Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        started = time.perf_counter()
        try:
            message = await asyncio.wait_for(
                self._chat.ainvoke([SystemMessage(content=system), HumanMessage(content=user)]), timeout=self._timeout
            )
        except TimeoutError:
            raise LLMError(f"LLM timed out after {self._timeout:.0f}s") from None
        except Exception as exc:
            raise LLMError(f"LLM call failed: {type(exc).__name__}: {exc}") from None
        duration = round((time.perf_counter() - started) * 1000, 1)
        usage = getattr(message, "usage_metadata", None) or {}
        log_event(
            logger,
            "llm_call",
            purpose=purpose,
            model=self.model,
            duration_ms=duration,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        return parse_json_object(str(message.content))


def create_llm(settings: CopilotSettings) -> LLMClient:
    if settings.llm_provider == "ollama":
        return OllamaLLM(settings)
    return NullLLM()


def dumps_compact(value: Any, limit: int | None = None) -> str:
    text = json.dumps(value, default=str, separators=(",", ":"), ensure_ascii=False)
    return text if limit is None or len(text) <= limit else text[:limit] + "...(truncated)"
