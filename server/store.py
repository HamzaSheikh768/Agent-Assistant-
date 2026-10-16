from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, ThreadItem, ThreadMetadata

T = TypeVar("T")


def _page(records: list[T], after: str | None, limit: int) -> Page[T]:
    start = 0
    if after:
        start = next(
            (index + 1 for index, record in enumerate(records) if record.id == after),
            len(records),
        )

    selected = records[start : start + limit]
    has_more = start + limit < len(records)
    return Page(
        data=selected,
        has_more=has_more,
        after=selected[-1].id if selected and has_more else None,
    )


class MemoryStore(Store[dict[str, Any]]):
    """Small development store. Replace with a database before production."""

    def __init__(self) -> None:
        self._threads: dict[str, ThreadMetadata] = {}
        self._items: dict[str, list[ThreadItem]] = {}
        self._attachments: dict[str, Attachment] = {}
        self._lock = asyncio.Lock()

    async def load_thread(
        self, thread_id: str, context: dict[str, Any]
    ) -> ThreadMetadata:
        try:
            return self._threads[thread_id].model_copy(deep=True)
        except KeyError as error:
            raise NotFoundError(f"Thread {thread_id} was not found") from error

    async def save_thread(
        self, thread: ThreadMetadata, context: dict[str, Any]
    ) -> None:
        async with self._lock:
            self._threads[thread.id] = thread.model_copy(deep=True)
            self._items.setdefault(thread.id, [])

    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadItem]:
        if thread_id not in self._threads:
            raise NotFoundError(f"Thread {thread_id} was not found")

        items = [item.model_copy(deep=True) for item in self._items[thread_id]]
        if order == "desc":
            items.reverse()
        return _page(items, after, limit)

    async def save_attachment(
        self, attachment: Attachment, context: dict[str, Any]
    ) -> None:
        async with self._lock:
            self._attachments[attachment.id] = attachment.model_copy(deep=True)

    async def load_attachment(
        self, attachment_id: str, context: dict[str, Any]
    ) -> Attachment:
        try:
            return self._attachments[attachment_id].model_copy(deep=True)
        except KeyError as error:
            raise NotFoundError(
                f"Attachment {attachment_id} was not found"
            ) from error

    async def delete_attachment(
        self, attachment_id: str, context: dict[str, Any]
    ) -> None:
        async with self._lock:
            self._attachments.pop(attachment_id, None)

    async def load_threads(
        self,
        limit: int,
        after: str | None,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadMetadata]:
        threads = sorted(
            (thread.model_copy(deep=True) for thread in self._threads.values()),
            key=lambda thread: thread.created_at,
            reverse=order == "desc",
        )
        return _page(threads, after, limit)

    async def add_thread_item(
        self,
        thread_id: str,
        item: ThreadItem,
        context: dict[str, Any],
    ) -> None:
        async with self._lock:
            if thread_id not in self._threads:
                raise NotFoundError(f"Thread {thread_id} was not found")
            self._items[thread_id].append(item.model_copy(deep=True))

    async def save_item(
        self,
        thread_id: str,
        item: ThreadItem,
        context: dict[str, Any],
    ) -> None:
        async with self._lock:
            if thread_id not in self._threads:
                raise NotFoundError(f"Thread {thread_id} was not found")
            items = self._items[thread_id]
            for index, existing in enumerate(items):
                if existing.id == item.id:
                    items[index] = item.model_copy(deep=True)
                    return
            items.append(item.model_copy(deep=True))

    async def load_item(
        self,
        thread_id: str,
        item_id: str,
        context: dict[str, Any],
    ) -> ThreadItem:
        for item in self._items.get(thread_id, []):
            if item.id == item_id:
                return item.model_copy(deep=True)
        raise NotFoundError(f"Item {item_id} was not found")

    async def delete_thread(
        self, thread_id: str, context: dict[str, Any]
    ) -> None:
        async with self._lock:
            self._threads.pop(thread_id, None)
            self._items.pop(thread_id, None)

    async def delete_thread_item(
        self,
        thread_id: str,
        item_id: str,
        context: dict[str, Any],
    ) -> None:
        async with self._lock:
            self._items[thread_id] = [
                item for item in self._items.get(thread_id, []) if item.id != item_id
            ]
