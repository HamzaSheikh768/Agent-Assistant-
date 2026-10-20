from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from chatkit.server import ChatKitServer
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageContentPartTextDelta,
    AssistantMessageItem,
    ProgressUpdateEvent,
    ThreadItemAddedEvent,
    ThreadItemDoneEvent,
    ThreadItemUpdatedEvent,
    ThreadMetadata,
    ThreadStreamEvent,
    UserMessageItem,
)

from server.gemini_agent import GeminiAgent
from server.observability import reset_request_id, set_request_id
from server.store import MemoryStore


class GeminiChatKitServer(ChatKitServer[dict[str, Any]]):
    def __init__(self, store: MemoryStore, agent: GeminiAgent) -> None:
        super().__init__(store)
        self.agent = agent

    async def respond(
        self,
        thread: ThreadMetadata,
        input_user_message: UserMessageItem | None,
        context: dict[str, Any],
    ) -> AsyncIterator[ThreadStreamEvent]:
        token = set_request_id(str(context.get("request_id", "unknown")))
        try:
            yield ProgressUpdateEvent(text="Thinking with Gemini…", icon="sparkle")

            items = []
            after = None
            while len(items) < 500:
                page = await self.store.load_thread_items(
                    thread.id,
                    after=after,
                    limit=min(100, 500 - len(items)),
                    order="desc",
                    context=context,
                )
                items.extend(page.data)
                if not page.has_more or not page.after:
                    break
                after = page.after
            items.reverse()

            message = AssistantMessageItem(
                id=self.store.generate_item_id("message", thread, context),
                thread_id=thread.id,
                created_at=datetime.now(),
                content=[AssistantMessageContent(text="")],
            )
            yield ThreadItemAddedEvent(item=message)

            full_text = ""
            async for delta in self.agent.stream(thread, items):
                full_text += delta
                yield ThreadItemUpdatedEvent(
                    item_id=message.id,
                    update=AssistantMessageContentPartTextDelta(
                        content_index=0,
                        delta=delta,
                    ),
                )

            message.content[0].text = full_text or "I could not generate a response."
            yield ThreadItemDoneEvent(item=message)

            if not thread.title and input_user_message:
                user_text = " ".join(
                    part.text
                    for part in input_user_message.content
                    if hasattr(part, "text")
                ).strip()
                if user_text:
                    thread.title = (
                        user_text[:44] + "…" if len(user_text) > 45 else user_text
                    )
        finally:
            await self.store.save_thread(thread, context)
            reset_request_id(token)
