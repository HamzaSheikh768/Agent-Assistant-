from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient

from chatkit.types import (
    InferenceOptions,
    ThreadMetadata,
    UserMessageItem,
    UserMessageTextContent,
)
from server.app import _authorize, app, health_live, server
from server.gemini_agent import GeminiAgent
from server.store import MemoryStore
from server.usage import Usage


def user_message(index: int, thread_id: str = "thread-1") -> UserMessageItem:
    return UserMessageItem(
        id=f"message-{index}",
        thread_id=thread_id,
        created_at=datetime.now(UTC),
        content=[UserMessageTextContent(text=f"message {index}")],
        inference_options=InferenceOptions(),
    )


class FakeStream:
    def __init__(self, texts: list[str]) -> None:
        self._chunks = iter(texts)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            text = next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None
        return SimpleNamespace(text=text, usage_metadata=None)


class FakeModels:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_content_stream(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise asyncio.TimeoutError("temporary")
        return FakeStream(["hello", " world"])


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_request_size_routes(self) -> None:
        transport = ASGITransport(app=app)
        with patch.dict(
            os.environ,
            {
                "CHATKIT_INTERNAL_TOKEN": "expected",
                "CHATKIT_MAX_REQUEST_BYTES": "10",
            },
        ):
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                live = await client.get("/health/live")
                ready = await client.get(
                    "/health/ready",
                    headers={"authorization": "Bearer expected"},
                )
                oversized = await client.post(
                    "/chatkit",
                    headers={"authorization": "Bearer expected"},
                    content=b"12345678901",
                )

        self.assertEqual(live.status_code, 200)
        self.assertTrue(live.headers.get("x-request-id"))
        self.assertIn(ready.status_code, {200, 503})
        self.assertEqual(oversized.status_code, 413)

    async def test_liveness_does_not_claim_provider_readiness(self) -> None:
        self.assertEqual(await health_live(), {"status": "alive"})
        self.assertIsInstance(server.agent.ready, bool)

    async def test_internal_auth_rejects_invalid_token(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/ready",
                "headers": [(b"authorization", b"Bearer wrong")],
            }
        )
        with patch.dict(os.environ, {"CHATKIT_INTERNAL_TOKEN": "expected"}):
            with self.assertRaises(HTTPException) as raised:
                _authorize(request)
        self.assertEqual(raised.exception.status_code, 401)

    async def test_store_keeps_threads_separate_and_returns_copies(self) -> None:
        store = MemoryStore()
        context = {"user_id": "local-demo-user"}
        first = ThreadMetadata(id="thread-1", created_at=datetime.now(UTC))
        second = ThreadMetadata(id="thread-2", created_at=datetime.now(UTC))
        await store.save_thread(first, context)
        await store.save_thread(second, context)
        await store.add_thread_item("thread-1", user_message(1), context)

        first_page = await store.load_thread_items(
            "thread-1", None, 10, "asc", context
        )
        second_page = await store.load_thread_items(
            "thread-2", None, 10, "asc", context
        )
        self.assertEqual(len(first_page.data), 1)
        self.assertEqual(second_page.data, [])
        loaded = await store.load_thread("thread-1", context)
        loaded.title = "changed outside store"
        self.assertIsNone((await store.load_thread("thread-1", context)).title)

    async def test_stream_retries_before_first_token(self) -> None:
        agent = GeminiAgent()
        models = FakeModels()
        agent.client = SimpleNamespace(aio=SimpleNamespace(models=models))
        agent.max_retries = 1
        agent._prepare_history = AsyncMock(return_value=([], 10))  # type: ignore[method-assign]
        agent.usage = SimpleNamespace(
            ensure_budget=AsyncMock(),
            record=AsyncMock(),
        )
        thread = ThreadMetadata(id="thread-1", created_at=datetime.now(UTC))

        with patch("server.gemini_agent.asyncio.sleep", new=AsyncMock()):
            chunks = [chunk async for chunk in agent.stream(thread, [])]

        self.assertEqual(chunks, ["hello", " world"])
        self.assertEqual(models.calls, 2)
        agent.usage.record.assert_awaited_once_with(  # type: ignore[attr-defined]
            Usage(), "chat_response", agent.model
        )

    async def test_long_context_is_summarized_and_recent_turns_retained(self) -> None:
        agent = GeminiAgent()
        agent.client = object()  # type: ignore[assignment]
        agent.recent_items = 4
        agent.context_budget = 5_000
        agent.response_reserve = 1_000
        agent._count_tokens = AsyncMock(side_effect=[20_000, 800])  # type: ignore[method-assign]
        agent._summarize = AsyncMock(return_value="stable summary")  # type: ignore[method-assign]
        thread = ThreadMetadata(id="thread-1", created_at=datetime.now(UTC))
        items = [user_message(index) for index in range(20)]

        compacted, tokens = await agent._prepare_history(thread, items)

        self.assertEqual(tokens, 800)
        self.assertEqual(len(compacted), 5)
        self.assertEqual(thread.metadata["northstar_summary"], "stable summary")
        self.assertEqual(
            thread.metadata["northstar_summary_through_item_id"], "message-15"
        )


if __name__ == "__main__":
    unittest.main()
