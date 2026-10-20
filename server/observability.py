from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_request_id: ContextVar[str] = ContextVar("request_id", default="unknown")
_logger = logging.getLogger("northstar")
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
_logger.setLevel(logging.INFO)
_logger.propagate = False


def set_request_id(value: str) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


def current_request_id() -> str:
    return _request_id.get()


def log_event(level: str, event: str, **fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "service": "northstar-agent",
        "request_id": current_request_id(),
        **fields,
    }
    message = json.dumps(payload, default=str, separators=(",", ":"))
    getattr(_logger, level if level in {"info", "warning", "error"} else "info")(
        message
    )
