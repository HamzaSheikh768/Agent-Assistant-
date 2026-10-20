from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncIterator

import httpx
from chatkit.errors import CustomStreamError
from chatkit.types import (
    AssistantMessageItem,
    ThreadItem,
    ThreadMetadata,
    UserMessageItem,
)
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from server.observability import log_event
from server.usage import DailyBudgetExceeded, Usage, UsageTracker

SYSTEM_INSTRUCTION = """
You are Northstar, a helpful general-purpose assistant inside a ChatKit interface.
Answer directly, accurately, and concisely. Break complex work into clear steps.
Do not claim that an external action succeeded unless a tool or system response
confirms it. If important information is missing, state the assumption you make.
""".strip()


def _int_setting(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= minimum else default


def _float_setting(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _message_text(item: ThreadItem) -> str:
    if isinstance(item, UserMessageItem):
        return "\n".join(
            part.text for part in item.content if hasattr(part, "text")
        ).strip()
    if isinstance(item, AssistantMessageItem):
        return "\n".join(part.text for part in item.content).strip()
    return ""


def _history(items: list[ThreadItem]) -> list[types.Content]:
    history: list[types.Content] = []
    for item in items:
        text = _message_text(item)
        if not text:
            continue
        role = "user" if isinstance(item, UserMessageItem) else "model"
        history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=text)])
        )
    return history


def _summary_content(summary: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "Conversation summary from earlier turns. Treat this as context, "
                    f"not as a new user request:\n{summary}"
                )
            )
        ],
    )


def _usage(metadata: object | None) -> Usage:
    if metadata is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(metadata, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(metadata, "candidates_token_count", 0) or 0),
        thought_tokens=int(getattr(metadata, "thoughts_token_count", 0) or 0),
        total_tokens=int(getattr(metadata, "total_token_count", 0) or 0),
    )


def _is_transient(error: Exception) -> bool:
    if isinstance(
        error,
        (
            asyncio.TimeoutError,
            TimeoutError,
            ConnectionError,
            httpx.TransportError,
        ),
    ):
        return True
    if isinstance(error, genai_errors.APIError):
        return error.code == 429 or error.code >= 500
    return False


class GeminiAgent:
    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.usage = UsageTracker()
        self.context_budget = _int_setting("GEMINI_CONTEXT_TOKEN_BUDGET", 24_000, 1000)
        self.response_reserve = _int_setting("GEMINI_RESPONSE_TOKEN_RESERVE", 4_096, 256)
        self.recent_items = _int_setting("GEMINI_RECENT_ITEMS", 12, 2)
        self.max_retries = _int_setting("GEMINI_MAX_RETRIES", 2)
        self.first_token_timeout = _float_setting(
            "GEMINI_FIRST_TOKEN_TIMEOUT_SECONDS", 30
        )
        self.idle_timeout = _float_setting("GEMINI_IDLE_TIMEOUT_SECONDS", 30)
        self.overall_timeout = _float_setting("GEMINI_OVERALL_TIMEOUT_SECONDS", 120)
        self._health_lock = asyncio.Lock()
        self._health_checked_at = 0.0
        self._health_result: tuple[bool, str] = (
            (True, "ok") if self.client else (False, "missing_configuration")
        )

    @property
    def ready(self) -> bool:
        return self.client is not None

    async def readiness(self, cache_seconds: float = 60) -> tuple[bool, str]:
        if not self.client:
            return False, "missing_configuration"
        now = time.monotonic()
        if now - self._health_checked_at < cache_seconds:
            return self._health_result

        async with self._health_lock:
            now = time.monotonic()
            if now - self._health_checked_at < cache_seconds:
                return self._health_result
            try:
                await asyncio.wait_for(
                    self.client.aio.models.get(model=self.model),
                    timeout=10,
                )
                result = (True, "ok")
            except genai_errors.APIError as error:
                reasons = {
                    401: "unauthorized",
                    403: "permission_denied",
                    404: "model_not_found",
                    429: "rate_limited",
                }
                result = (False, reasons.get(error.code, "provider_error"))
            except (httpx.TransportError, asyncio.TimeoutError, TimeoutError):
                result = (False, "provider_unreachable")
            except Exception:
                result = (False, "provider_error")
            self._health_checked_at = time.monotonic()
            self._health_result = result
            return result

    async def _count_tokens(self, contents: list[types.Content]) -> int:
        if not contents:
            return 0
        if not self.client:
            return sum(len(str(content)) for content in contents) // 4
        try:
            result = await asyncio.wait_for(
                self.client.aio.models.count_tokens(
                    model=self.model,
                    contents=contents,
                    config=types.CountTokensConfig(
                        system_instruction=SYSTEM_INSTRUCTION
                    ),
                ),
                timeout=10,
            )
            return int(result.total_tokens or 0)
        except Exception as error:
            log_event(
                "warning",
                "gemini_token_count_fallback",
                error_type=type(error).__name__,
            )
            text_size = sum(
                len(getattr(part, "text", "") or "")
                for content in contents
                for part in (content.parts or [])
            )
            return max(1, text_size // 4)

    async def _summarize(
        self,
        previous_summary: str,
        older_items: list[ThreadItem],
    ) -> str:
        if not self.client:
            return previous_summary
        transcript = "\n\n".join(
            f"{'User' if isinstance(item, UserMessageItem) else 'Assistant'}: "
            f"{_message_text(item)}"
            for item in older_items
            if _message_text(item)
        )
        source = (
            f"Existing summary:\n{previous_summary}\n\nNew older turns:\n{transcript}"
            if previous_summary
            else transcript
        )
        source = source[-120_000:]
        await self.usage.ensure_budget(max(1, len(source) // 4))
        response = await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=self.model,
                contents=(
                    "Compress this conversation context faithfully. Preserve user goals, "
                    "constraints, decisions, facts, and unresolved tasks. Remove repetition. "
                    f"Do not answer the conversation.\n\n{source}"
                ),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1_200,
                ),
            ),
            timeout=30,
        )
        await self.usage.record(
            _usage(response.usage_metadata), "context_summary", self.model
        )
        return (response.text or previous_summary).strip()

    async def _prepare_history(
        self,
        thread: ThreadMetadata,
        items: list[ThreadItem],
    ) -> tuple[list[types.Content], int]:
        history = _history(items)
        tokens = await self._count_tokens(history)
        available = max(1_000, self.context_budget - self.response_reserve)
        if tokens <= available:
            return history, tokens

        recent = items[-self.recent_items :]
        cutoff = max(0, len(items) - len(recent))
        previous_summary = str(thread.metadata.get("northstar_summary", ""))
        cursor = thread.metadata.get("northstar_summary_through_item_id")
        start = 0
        if cursor:
            for index, item in enumerate(items):
                if item.id == cursor:
                    start = index + 1
                    break
        older = items[start:cutoff]

        try:
            summary = await self._summarize(previous_summary, older)
        except DailyBudgetExceeded:
            raise
        except Exception as error:
            log_event(
                "warning",
                "gemini_context_summary_failed",
                error_type=type(error).__name__,
            )
            summary = previous_summary

        if summary:
            thread.metadata["northstar_summary"] = summary
            if cutoff:
                thread.metadata["northstar_summary_through_item_id"] = items[
                    cutoff - 1
                ].id
            compacted = [_summary_content(summary), *_history(recent)]
        else:
            compacted = _history(recent)

        compacted_tokens = await self._count_tokens(compacted)
        log_event(
            "info",
            "conversation_context_compacted",
            original_items=len(items),
            retained_items=len(recent),
            original_tokens=tokens,
            compacted_tokens=compacted_tokens,
        )
        return compacted, compacted_tokens

    async def stream(
        self,
        thread: ThreadMetadata,
        items: list[ThreadItem],
    ) -> AsyncIterator[str]:
        if not self.client:
            raise CustomStreamError(
                "The AI service is not configured. Please contact the administrator.",
                allow_retry=False,
            )

        try:
            history, estimated_input = await self._prepare_history(thread, items)
            await self.usage.ensure_budget(estimated_input + self.response_reserve)
        except DailyBudgetExceeded as error:
            raise CustomStreamError(
                "The daily AI usage limit has been reached. Please try again later.",
                allow_retry=False,
            ) from error

        started = time.monotonic()
        latest_usage = Usage()
        for attempt in range(self.max_retries + 1):
            emitted = False
            try:
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content_stream(
                        model=self.model,
                        contents=history,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.4,
                            max_output_tokens=self.response_reserve,
                        ),
                    ),
                    timeout=self.first_token_timeout,
                )
                iterator = response.__aiter__()
                while True:
                    elapsed = time.monotonic() - started
                    if elapsed >= self.overall_timeout:
                        raise asyncio.TimeoutError("Gemini overall timeout")
                    timeout = min(
                        self.idle_timeout if emitted else self.first_token_timeout,
                        self.overall_timeout - elapsed,
                    )
                    try:
                        chunk = await asyncio.wait_for(iterator.__anext__(), timeout)
                    except StopAsyncIteration:
                        break
                    if chunk.usage_metadata is not None:
                        latest_usage = _usage(chunk.usage_metadata)
                    if chunk.text:
                        emitted = True
                        yield chunk.text

                await self.usage.record(latest_usage, "chat_response", self.model)
                log_event(
                    "info",
                    "gemini_stream_completed",
                    duration_ms=round((time.monotonic() - started) * 1000),
                    retries=attempt,
                )
                return
            except Exception as error:
                if latest_usage.total_tokens:
                    await self.usage.record(latest_usage, "chat_response_partial", self.model)
                    latest_usage = Usage()
                transient = _is_transient(error)
                log_event(
                    "warning" if transient else "error",
                    "gemini_stream_error",
                    error_type=type(error).__name__,
                    provider_status=getattr(error, "code", None),
                    attempt=attempt + 1,
                    emitted=emitted,
                    transient=transient,
                )
                if transient and not emitted and attempt < self.max_retries:
                    await asyncio.sleep((0.5 * (2**attempt)) + random.uniform(0, 0.25))
                    continue
                if isinstance(error, genai_errors.APIError) and error.code == 429:
                    message = "The AI provider is busy or over quota. Please retry shortly."
                elif isinstance(error, genai_errors.APIError) and error.code in {401, 403}:
                    message = (
                        "The AI provider denied access. Check the Gemini API key and "
                        "project permissions."
                    )
                elif isinstance(error, (asyncio.TimeoutError, TimeoutError)):
                    message = "The AI provider timed out. Please retry."
                else:
                    message = "The AI provider could not complete this response."
                raise CustomStreamError(message, allow_retry=transient) from error
