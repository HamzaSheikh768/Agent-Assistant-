import { randomUUID } from "node:crypto";

import { NextRequest } from "next/server";

import {
  getChatkitEndpoint,
  getChatkitPublicFallbackEndpoint,
} from "@/lib/chatkit-backend";
import { enforceRateLimit } from "@/lib/rate-limit";
import {
  contentLengthExceedsLimit,
  maxRequestBytes,
  positiveInteger,
} from "@/lib/request-policy";
import { serverLog } from "@/lib/server-log";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function requestId(request: NextRequest): string {
  const supplied = request.headers.get("x-request-id");
  if (supplied && /^[a-zA-Z0-9._-]{1,100}$/.test(supplied)) {
    return supplied;
  }
  return randomUUID();
}

function jsonError(
  status: number,
  code: string,
  message: string,
  id: string,
  headers?: HeadersInit,
): Response {
  return Response.json(
    { error: { code, message, requestId: id } },
    { status, headers: { "x-request-id": id, ...headers } },
  );
}

function streamingBody(
  body: ReadableStream<Uint8Array> | null,
  fields: Record<string, unknown>,
): ReadableStream<Uint8Array> | null {
  if (!body) {
    return null;
  }

  const reader = body.getReader();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) {
          serverLog("info", "chatkit_stream_completed", fields);
          controller.close();
        } else {
          controller.enqueue(chunk.value);
        }
      } catch (error) {
        serverLog("error", "chatkit_stream_failed", {
          ...fields,
          errorType: error instanceof Error ? error.name : "UnknownError",
        });
        controller.error(error);
      }
    },
    async cancel(reason) {
      await reader.cancel(reason);
    },
  });
}

export async function POST(request: NextRequest) {
  const id = requestId(request);
  const startedAt = performance.now();
  const internalToken = process.env.CHATKIT_INTERNAL_TOKEN;
  const sizeLimit = maxRequestBytes();

  if (!internalToken) {
    serverLog("error", "chatkit_configuration_error", {
      requestId: id,
      missing: "CHATKIT_INTERNAL_TOKEN",
    });
    return jsonError(
      503,
      "service_not_configured",
      "The chat service is not configured.",
      id,
    );
  }

  if (contentLengthExceedsLimit(request.headers.get("content-length"), sizeLimit)) {
    return jsonError(
      413,
      "request_too_large",
      "The request is larger than the allowed limit.",
      id,
    );
  }

  const rateLimit = await enforceRateLimit(request.headers);
  const rateHeaders = {
    "x-ratelimit-limit": String(rateLimit.limit),
    "x-ratelimit-remaining": String(rateLimit.remaining),
  };
  if (!rateLimit.allowed) {
    serverLog("warn", "chatkit_rate_limited", {
      requestId: id,
      backend: rateLimit.backend,
    });
    return jsonError(
      429,
      "rate_limit_exceeded",
      "Too many requests. Please try again later.",
      id,
      {
        ...rateHeaders,
        "retry-after": String(rateLimit.retryAfterSeconds),
      },
    );
  }

  let body: ArrayBuffer;
  try {
    body = await request.arrayBuffer();
  } catch {
    return jsonError(400, "invalid_request", "The request body is invalid.", id);
  }
  if (body.byteLength > sizeLimit) {
    return jsonError(
      413,
      "request_too_large",
      "The request is larger than the allowed limit.",
      id,
    );
  }

  const timeoutMs = positiveInteger(process.env.CHATKIT_UPSTREAM_TIMEOUT_MS, 30_000);
  const timeoutController = new AbortController();
  const timeout = setTimeout(() => timeoutController.abort(), timeoutMs);
  const upstreamHeaders = {
    authorization: `Bearer ${internalToken}`,
    "content-type": request.headers.get("content-type") ?? "application/json",
    "x-request-id": id,
  };
  const upstreamSignal = AbortSignal.any([
    request.signal,
    timeoutController.signal,
  ]);
  let fallbackAttempted = false;

  try {
    let upstream: Response;
    let transport = "service_binding";

    try {
      upstream = await fetch(getChatkitEndpoint(), {
        method: "POST",
        headers: upstreamHeaders,
        body,
        cache: "no-store",
        signal: upstreamSignal,
      });
    } catch (bindingError) {
      const fallbackEndpoint = getChatkitPublicFallbackEndpoint(
        request.nextUrl.origin,
      );
      if (!fallbackEndpoint || upstreamSignal.aborted) {
        throw bindingError;
      }

      fallbackAttempted = true;
      transport = "public_service_fallback";
      serverLog("warn", "chatkit_upstream_fallback", {
        requestId: id,
        durationMs: Math.round(performance.now() - startedAt),
        errorType:
          bindingError instanceof Error ? bindingError.name : "UnknownError",
      });
      upstream = await fetch(fallbackEndpoint, {
        method: "POST",
        headers: upstreamHeaders,
        body,
        cache: "no-store",
        signal: upstreamSignal,
      });
    }
    clearTimeout(timeout);

    const responseHeaders = new Headers(rateHeaders);
    responseHeaders.set("x-request-id", id);
    responseHeaders.set(
      "content-type",
      upstream.headers.get("content-type") ?? "application/json",
    );
    responseHeaders.set("cache-control", "no-cache, no-transform");
    responseHeaders.set("x-accel-buffering", "no");

    serverLog(upstream.ok ? "info" : "warn", "chatkit_upstream_response", {
      requestId: id,
      status: upstream.status,
      durationMs: Math.round(performance.now() - startedAt),
      requestBytes: body.byteLength,
      rateLimitBackend: rateLimit.backend,
      transport,
    });

    return new Response(
      streamingBody(upstream.body, {
        requestId: id,
        status: upstream.status,
      }),
      { status: upstream.status, headers: responseHeaders },
    );
  } catch (error) {
    clearTimeout(timeout);
    const timedOut = timeoutController.signal.aborted;
    serverLog("error", "chatkit_upstream_unavailable", {
      requestId: id,
      durationMs: Math.round(performance.now() - startedAt),
      timedOut,
      errorType: error instanceof Error ? error.name : "UnknownError",
    });
    return jsonError(
      timedOut ? 504 : 503,
      timedOut ? "upstream_timeout" : "service_unavailable",
      timedOut
        ? "The chat service timed out. Please retry."
        : "The chat service is temporarily unavailable.",
      id,
      {
        ...rateHeaders,
        "x-chatkit-fallback": fallbackAttempted ? "attempted" : "unavailable",
      },
    );
  }
}
