from __future__ import annotations

import hmac
import os
import re
import time
import uuid

import truststore
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from chatkit.server import StreamingResult
from server.chatkit_server import GeminiChatKitServer
from server.gemini_agent import GeminiAgent
from server.observability import log_event, reset_request_id, set_request_id
from server.store import MemoryStore

truststore.inject_into_ssl()

app = FastAPI(
    title="Northstar ChatKit agent",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
store = MemoryStore()
server = GeminiChatKitServer(store, GeminiAgent())


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    if re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", supplied):
        return supplied
    return str(uuid.uuid4())


def _authorize(request: Request) -> None:
    expected = os.getenv("CHATKIT_INTERNAL_TOKEN")
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid internal token")


@app.middleware("http")
async def request_observability(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = _request_id(request)
    token = set_request_id(request_id)
    started = time.monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as error:
        log_event(
            "error",
            "unhandled_request_error",
            method=request.method,
            path=request.url.path,
            error_type=type(error).__name__,
        )
        response = JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The service could not process this request.",
                    "requestId": request_id,
                }
            },
        )
    response.headers["x-request-id"] = request_id
    log_event(
        "info",
        "http_request_completed",
        method=request.method,
        path=request.url.path,
        status=status_code,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    reset_request_id(token)
    return response


async def _readiness_response() -> JSONResponse:
    provider_ready, provider_status = await server.agent.readiness()
    ready = provider_ready and bool(os.getenv("CHATKIT_INTERNAL_TOKEN"))
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "unavailable",
            "checks": {
                "gemini": provider_status,
                "internal_auth": (
                    "ok" if os.getenv("CHATKIT_INTERNAL_TOKEN") else "missing_configuration"
                ),
            },
            "model": server.agent.model,
        },
        headers={"cache-control": "no-store"},
    )


@app.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    _authorize(request)
    return await _readiness_response()


@app.post("/chatkit")
async def chatkit_endpoint(request: Request) -> Response:
    _authorize(request)
    max_bytes = _positive_int("CHATKIT_MAX_REQUEST_BYTES", 1_048_576)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="Request body is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid content-length") from None

    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="Request body is too large")

    try:
        result = await server.process(
            body,
            {
                "user_id": "local-demo-user",
                "request_id": request.headers.get("x-request-id", "unknown"),
            },
        )
    except (ValidationError, ValueError, UnicodeDecodeError) as error:
        log_event(
            "warning",
            "invalid_chatkit_request",
            error_type=type(error).__name__,
        )
        raise HTTPException(status_code=400, detail="Invalid ChatKit request") from error
    except HTTPException:
        raise
    except Exception as error:
        log_event(
            "error",
            "chatkit_processing_failed",
            error_type=type(error).__name__,
        )
        raise HTTPException(
            status_code=500, detail="The ChatKit request could not be processed"
        ) from error

    if isinstance(result, StreamingResult):
        return StreamingResponse(
            result,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return Response(content=result.json, media_type="application/json")
