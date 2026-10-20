import { createHash } from "node:crypto";

import { positiveInteger } from "@/lib/request-policy";
import { serverLog } from "@/lib/server-log";

type WindowResult = {
  allowed: boolean;
  limit: number;
  remaining: number;
  retryAfterSeconds: number;
};

type RateLimitResult = WindowResult & {
  backend: "redis" | "memory";
};

type MemoryCounter = { count: number; expiresAt: number };

const globalCounters = globalThis as typeof globalThis & {
  __northstarRateLimits?: Map<string, MemoryCounter>;
};

const counters =
  globalCounters.__northstarRateLimits ?? new Map<string, MemoryCounter>();
globalCounters.__northstarRateLimits = counters;

function clientIdentifier(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const source = forwarded || headers.get("x-real-ip") || "unknown";
  return createHash("sha256")
    .update(`${process.env.RATE_LIMIT_SALT ?? "northstar"}:${source}`)
    .digest("hex")
    .slice(0, 32);
}

function memoryIncrement(key: string, ttlSeconds: number): number {
  const now = Date.now();
  const existing = counters.get(key);
  if (!existing || existing.expiresAt <= now) {
    counters.set(key, { count: 1, expiresAt: now + ttlSeconds * 1_000 });
    return 1;
  }
  existing.count += 1;
  return existing.count;
}

async function redisIncrements(
  minuteKey: string,
  dayKey: string,
): Promise<[number, number] | null> {
  const url = process.env.UPSTASH_REDIS_REST_URL?.replace(/\/+$/, "");
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) {
    return null;
  }

  const response = await fetch(`${url}/pipeline`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify([
      ["INCR", minuteKey],
      ["EXPIRE", minuteKey, 60, "NX"],
      ["INCR", dayKey],
      ["EXPIRE", dayKey, 86_400, "NX"],
    ]),
    cache: "no-store",
    signal: AbortSignal.timeout(1_500),
  });

  if (!response.ok) {
    throw new Error(`Redis rate limiter returned ${response.status}`);
  }

  const data = (await response.json()) as Array<{ result?: unknown }>;
  const minute = Number(data[0]?.result);
  const day = Number(data[2]?.result);
  if (!Number.isFinite(minute) || !Number.isFinite(day)) {
    throw new Error("Redis rate limiter returned an invalid response");
  }
  return [minute, day];
}

export async function enforceRateLimit(headers: Headers): Promise<RateLimitResult> {
  const perMinute = positiveInteger(
    process.env.CHATKIT_RATE_LIMIT_PER_MINUTE,
    20,
  );
  const perDay = positiveInteger(process.env.CHATKIT_RATE_LIMIT_PER_DAY, 500);
  const identifier = clientIdentifier(headers);
  const minuteBucket = Math.floor(Date.now() / 60_000);
  const dayBucket = Math.floor(Date.now() / 86_400_000);
  const minuteKey = `northstar:rate:${identifier}:m:${minuteBucket}`;
  const dayKey = `northstar:rate:${identifier}:d:${dayBucket}`;

  let counts: [number, number] | null = null;
  let backend: RateLimitResult["backend"] = "redis";
  try {
    counts = await redisIncrements(minuteKey, dayKey);
  } catch (error) {
    serverLog("warn", "rate_limit_redis_unavailable", {
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
  }

  if (!counts) {
    backend = "memory";
    counts = [
      memoryIncrement(minuteKey, 60),
      memoryIncrement(dayKey, 86_400),
    ];
  }

  const [minuteCount, dayCount] = counts;
  const minuteRemaining = Math.max(0, perMinute - minuteCount);
  const dayRemaining = Math.max(0, perDay - dayCount);
  const allowed = minuteCount <= perMinute && dayCount <= perDay;
  const retryAfterSeconds = minuteCount > perMinute ? 60 : 86_400;

  return {
    allowed,
    limit: Math.min(perMinute, perDay),
    remaining: Math.min(minuteRemaining, dayRemaining),
    retryAfterSeconds,
    backend,
  };
}
