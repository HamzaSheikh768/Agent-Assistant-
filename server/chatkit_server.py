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
        yield ProgressUpdateEvent(text="Thinking with Gemini…", icon="sparkle")

        page = await self.store.load_thread_items(
            thread.id,
            after=None,
            limit=40,
            order="asc",
            context=context,
        )

        message = AssistantMessageItem(
            id=self.store.generate_item_id("message", thread, context),
            thread_id=thread.id,
            created_at=datetime.now(),
            content=[AssistantMessageContent(text="")],
        )
        yield ThreadItemAddedEvent(item=message)

        full_text = ""
        async for delta in self.agent.stream(page.data):
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
