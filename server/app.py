from __future__ import annotations

import hmac
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from chatkit.server import StreamingResult
from server.chatkit_server import GeminiChatKitServer
from server.gemini_agent import GeminiAgent
from server.store import MemoryStore

load_dotenv("server/.env")

app = FastAPI(title="Northstar ChatKit agent", version="0.1.0")
store = MemoryStore()
server = GeminiChatKitServer(store, GeminiAgent())


def _authorize(request: Request) -> None:
    expected = os.getenv("CHATKIT_INTERNAL_TOKEN")
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid internal token")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": server.agent.model}


@app.post("/chatkit")
async def chatkit_endpoint(request: Request) -> Response:
    _authorize(request)
    result = await server.process(
        await request.body(),
        {"user_id": "local-demo-user"},
    )

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
