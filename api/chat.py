"""Streaming chat endpoint with frontend-action and internal-query tools.

Wire SSE event stream so the frontend can distinguish:
- `text`              partial assistant text (streamed deltas)
- `tool_used`         server-side internal tool ran (informational)
- `frontend_action`   AI requests a UI change; frontend executes it
- `session`           server-assigned session id for follow-up turns
- `notice`            non-fatal warning (e.g. unknown / missing session id)
- `done`              stream finished
- `error`             stream aborted
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from tools.frontend import ChatDeps, Coord, sse
from taipei_agent.taipei_agent import TaipeiAgent


# --- in-memory session store with LRU + per-session message cap ---


MAX_SESSIONS = 1000
MAX_MESSAGES_PER_SESSION = 40

_sessions: "OrderedDict[str, list[ModelMessage]]" = OrderedDict()


def _load_session(session_id: str) -> list[ModelMessage]:
    """Touch session for LRU and return its history (empty if new)."""
    if session_id in _sessions:
        _sessions.move_to_end(session_id)
        return list(_sessions[session_id])
    return []


def _trim_history(history: list[ModelMessage]) -> list[ModelMessage]:
    """Keep at most MAX_MESSAGES_PER_SESSION, cutting at a user-turn boundary
    so that tool-call / tool-return pairs stay intact."""
    if len(history) <= MAX_MESSAGES_PER_SESSION:
        return history

    keep_from_end = MAX_MESSAGES_PER_SESSION
    cut = None
    # Search backwards for a ModelRequest containing a UserPromptPart;
    # cutting there keeps each preserved turn whole.
    for i in range(len(history) - keep_from_end, -1, -1):
        msg = history[i]
        if isinstance(msg, ModelRequest) and any(
            isinstance(p, UserPromptPart) for p in msg.parts
        ):
            cut = i
            break

    if cut is None or cut == 0:
        return history
    return history[cut:]


def _save_session(session_id: str, history: list[ModelMessage]) -> None:
    _sessions[session_id] = _trim_history(history)
    _sessions.move_to_end(session_id)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)  # evict oldest


# --- request / streaming pipeline ---


class Coordinate(BaseModel):
    lat: float
    lon: float


class ChatRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    start: Coordinate | None = None
    target: Coordinate | None = None


async def _run_agent(
    agent: TaipeiAgent,
    deps: ChatDeps,
    prompt: str,
    history: list[ModelMessage],
) -> None:
    """Background task: drive the agent and push events into the queue."""
    try:
        async with agent.chat_stream(prompt, deps=deps, message_history=history) as result:
            async for delta in result.stream_text(delta=True):
                await deps.event_queue.put(sse("text", {"delta": delta}))
            new_history = result.all_messages()
            _save_session(deps.session_id, new_history)
            await deps.event_queue.put(
                sse(
                    "done",
                    {
                        "session_id": deps.session_id,
                        "message_count": len(new_history),
                    },
                )
            )
    except Exception as e:
        await deps.event_queue.put(
            sse("error", {"message": f"{type(e).__name__}: {e}"})
        )
    finally:
        await deps.event_queue.put(None)  # sentinel: stream done


async def _sse_generator(agent: TaipeiAgent, req: ChatRequest) -> AsyncIterator[str]:
    requested = req.session_id
    if requested and requested in _sessions:
        session_id = requested
        history = _load_session(session_id)
        is_new = False
        notice = None
    elif not requested:
        session_id = str(uuid.uuid4())
        history = []
        is_new = True
        notice = {
            "level": "warn",
            "code": "SESSION_EMPTY",
            "message": "UUID IS EMPTY, NOW IS NEW SESSION",
        }
    else:
        session_id = str(uuid.uuid4())
        history = []
        is_new = True
        notice = {
            "level": "warn",
            "code": "SESSION_NOT_FOUND",
            "message": f"UUID '{requested}' NOT FOUND, NOW IS NEW SESSION",
        }

    if notice:
        yield sse("notice", notice)

    # Tell client which session_id to use for follow-up turns,
    # before any model output. Clients should overwrite their
    # cached session_id with this value when `is_new` is true.
    yield sse(
        "session",
        {
            "session_id": session_id,
            "is_new": is_new,
            "requested": requested,
        },
    )

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    deps = ChatDeps(
        event_queue=queue,
        session_id=session_id,
        start=Coord(lat=req.start.lat, lon=req.start.lon) if req.start else None,
        target=Coord(lat=req.target.lat, lon=req.target.lon) if req.target else None,
    )

    runner = asyncio.create_task(_run_agent(agent, deps, req.prompt, history))

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if not runner.done():
            runner.cancel()


# --- router ---


router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    agent: TaipeiAgent = request.app.state.agent
    return StreamingResponse(
        _sse_generator(agent, req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/chat/session/{session_id}")
async def reset_session(session_id: str) -> dict:
    _sessions.pop(session_id, None)
    return {"ok": True}
