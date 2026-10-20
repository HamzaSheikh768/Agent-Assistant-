from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import URLError
from urllib.request import Request, urlopen

from server.observability import log_event


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _nonnegative_decimal(name: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, "0"))
    except Exception:
        return Decimal(0)
    return max(value, Decimal(0))


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    total_tokens: int = 0


class DailyBudgetExceeded(RuntimeError):
    pass


class UsageTracker:
    def __init__(self) -> None:
        self.daily_budget = _positive_int("GEMINI_DAILY_TOKEN_BUDGET", 0)
        if os.getenv("GEMINI_DAILY_TOKEN_BUDGET", "0").strip() in {"", "0"}:
            self.daily_budget = 0
        self.input_price = _nonnegative_decimal("GEMINI_INPUT_USD_PER_MILLION")
        self.output_price = _nonnegative_decimal("GEMINI_OUTPUT_USD_PER_MILLION")
        self._memory: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _redis_config(self) -> tuple[str, str] | None:
        url = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
        return (url, token) if url and token else None

    async def _redis_command(self, command: list[object]) -> int | None:
        config = self._redis_config()
        if not config:
            return None
        url, token = config

        def send() -> int:
            request = Request(
                f"{url}/pipeline",
                data=json.dumps([command]).encode(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(request, timeout=2) as response:  # noqa: S310
                payload = json.loads(response.read())
            return int(payload[0]["result"] or 0)

        try:
            return await asyncio.to_thread(send)
        except (OSError, URLError, ValueError, KeyError, TypeError) as error:
            log_event(
                "warning",
                "usage_redis_unavailable",
                error_type=type(error).__name__,
            )
            return None

    async def used_today(self) -> int:
        day = self._day()
        key = f"northstar:usage:tokens:{day}"
        redis_value = await self._redis_command(["GET", key])
        if redis_value is not None:
            return redis_value
        async with self._lock:
            return self._memory.get(day, 0)

    async def ensure_budget(self, estimated_tokens: int = 0) -> None:
        if not self.daily_budget:
            return
        used = await self.used_today()
        if used + max(0, estimated_tokens) >= self.daily_budget:
            log_event(
                "warning",
                "gemini_daily_budget_blocked",
                used_tokens=used,
                budget_tokens=self.daily_budget,
            )
            raise DailyBudgetExceeded("Daily Gemini token budget reached")

    async def record(self, usage: Usage, operation: str, model: str) -> None:
        total = max(usage.total_tokens, usage.input_tokens + usage.output_tokens)
        day = self._day()
        key = f"northstar:usage:tokens:{day}"
        redis_total = await self._redis_command(["INCRBY", key, total])
        if redis_total is not None:
            await self._redis_command(["EXPIRE", key, 172800, "NX"])
            daily_total = redis_total
            backend = "redis"
        else:
            async with self._lock:
                self._memory[day] = self._memory.get(day, 0) + total
                daily_total = self._memory[day]
            backend = "memory"

        cost = (
            Decimal(usage.input_tokens) * self.input_price
            + Decimal(usage.output_tokens) * self.output_price
        ) / Decimal(1_000_000)
        log_event(
            "info",
            "gemini_usage",
            operation=operation,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            thought_tokens=usage.thought_tokens,
            total_tokens=total,
            daily_total_tokens=daily_total,
            daily_budget_tokens=self.daily_budget,
            estimated_cost_usd=str(cost.quantize(Decimal("0.000001"))),
            usage_backend=backend,
        )
