"""Streaming chat endpoint with frontend-action and internal-query tools.

Wire SSE event stream so the frontend can distinguish:
- `text`              partial assistant text (streamed deltas)
- `tool_used`         server-side internal tool ran (informational)
- `frontend_action`   AI requests a UI change; frontend executes it
- `done`              stream finished
- `error`             stream aborted
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL, TWCC_LLAMA_FFM_MODEL


# --- SSE event helpers ---


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --- per-run dependencies (shared with tools) ---


@dataclass
class ChatDeps:
    event_queue: asyncio.Queue[str | None]
    session_id: str


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


# --- agent + tools ---


def _build_agent() -> Agent[ChatDeps, str]:
    model = OpenAIChatModel(
        TWCC_LLAMA_FFM_MODEL,
        provider=OpenAIProvider(
            base_url=TWCC_LLAMA_FFM_API_URL,
            api_key=TWCC_LLAMA_FFM_API_KEY,
        ),
    )
    agent = Agent[ChatDeps, str](
        model=model,
        deps_type=ChatDeps,
        system_prompt=(
            "You are an assistant for the Taipei City Dashboard. "
            "Use the provided tools to query data and to control the UI. "
            "When the user asks to focus on a district, open a dashboard, or "
            "toggle a map layer, call the corresponding frontend tool. "
            "When you need data, call the internal query tools. "
            "Reply in zh-TW unless the user writes in English."
        ),
    )

    # ----- internal tools (server-side, results fed back to model) -----

    @agent.tool
    async def get_district_stats(ctx: RunContext[ChatDeps], district: str) -> dict:
        """Return mock population and area stats for a Taipei district."""
        data = {
            "信義區": {"population": 217000, "area_km2": 11.2},
            "大安區": {"population": 308000, "area_km2": 11.4},
            "中正區": {"population": 159000, "area_km2": 7.6},
        }.get(district, {"population": 0, "area_km2": 0})
        await ctx.deps.event_queue.put(
            _sse("tool_used", {"name": "get_district_stats", "args": {"district": district}})
        )
        return data

    @agent.tool
    async def search_dataset(ctx: RunContext[ChatDeps], keyword: str) -> list[str]:
        """Search known dashboard datasets by keyword."""
        catalog = ["人口統計", "交通流量", "空氣品質", "公共自行車", "犯罪熱點"]
        hits = [d for d in catalog if keyword in d]
        await ctx.deps.event_queue.put(
            _sse("tool_used", {"name": "search_dataset", "args": {"keyword": keyword}})
        )
        return hits

    # ----- frontend tools (fire-and-forget UI commands) -----

    async def _emit_frontend_action(
        ctx: RunContext[ChatDeps], action: str, params: dict
    ) -> str:
        action_id = f"fa_{uuid.uuid4().hex[:8]}"
        await ctx.deps.event_queue.put(
            _sse(
                "frontend_action",
                {"id": action_id, "action": action, "params": params},
            )
        )
        return f"queued:{action_id}"

    @agent.tool
    async def focus_district(ctx: RunContext[ChatDeps], district: str) -> str:
        """Pan/zoom the map to focus on a Taipei district."""
        return await _emit_frontend_action(ctx, "focus_district", {"district": district})

    @agent.tool
    async def open_dashboard(ctx: RunContext[ChatDeps], dashboard_id: str) -> str:
        """Open a named dashboard panel in the UI."""
        return await _emit_frontend_action(ctx, "open_dashboard", {"dashboard_id": dashboard_id})

    @agent.tool
    async def toggle_layer(
        ctx: RunContext[ChatDeps], layer: str, visible: bool
    ) -> str:
        """Show or hide a map overlay layer."""
        return await _emit_frontend_action(
            ctx, "toggle_layer", {"layer": layer, "visible": visible}
        )

    return agent


_AGENT = _build_agent()


# --- request / streaming pipeline ---


class ChatRequest(BaseModel):
    prompt: str
    session_id: str | None = None


async def _run_agent(deps: ChatDeps, prompt: str, history: list[ModelMessage]) -> None:
    """Background task: drive the agent and push events into the queue."""
    try:
        async with _AGENT.run_stream(prompt, deps=deps, message_history=history) as result:
            async for delta in result.stream_text(delta=True):
                await deps.event_queue.put(_sse("text", {"delta": delta}))
            new_history = result.all_messages()
            _save_session(deps.session_id, new_history)
            await deps.event_queue.put(
                _sse(
                    "done",
                    {
                        "session_id": deps.session_id,
                        "message_count": len(new_history),
                    },
                )
            )
    except Exception as e:
        await deps.event_queue.put(
            _sse("error", {"message": f"{type(e).__name__}: {e}"})
        )
    finally:
        await deps.event_queue.put(None)  # sentinel: stream done


async def _sse_generator(req: ChatRequest) -> AsyncIterator[str]:
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
        yield _sse("notice", notice)

    # Tell client which session_id to use for follow-up turns,
    # before any model output. Clients should overwrite their
    # cached session_id with this value when `is_new` is true.
    yield _sse(
        "session",
        {
            "session_id": session_id,
            "is_new": is_new,
            "requested": requested,
        },
    )

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    deps = ChatDeps(event_queue=queue, session_id=session_id)

    runner = asyncio.create_task(_run_agent(deps, req.prompt, history))

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
async def chat(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _sse_generator(req),
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
