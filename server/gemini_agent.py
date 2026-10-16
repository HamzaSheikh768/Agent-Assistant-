from __future__ import annotations

import os
from collections.abc import AsyncIterator

from chatkit.types import AssistantMessageItem, ThreadItem, UserMessageItem
from google import genai
from google.genai import types

SYSTEM_INSTRUCTION = """
You are Northstar, a helpful general-purpose assistant inside a ChatKit interface.
Answer directly, accurately, and concisely. Break complex work into clear steps.
Do not claim that an external action succeeded unless a tool or system response
confirms it. If important information is missing, state the assumption you make.
""".strip()


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


class GeminiAgent:
    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required")

        self.model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.client = genai.Client(api_key=api_key)

    async def stream(self, items: list[ThreadItem]) -> AsyncIterator[str]:
        response = await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=_history(items),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.4,
            ),
        )

        async for chunk in response:
            if chunk.text:
                yield chunk.text
