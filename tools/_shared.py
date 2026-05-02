"""Shared primitives for the agent's toolsets.

`ChatDeps` is the per-request container the agent threads through every
tool call via `RunContext`. It carries:
  - `event_queue`: the SSE queue that streams response events back to the
    browser. Tools push `frontend_action` frames the client executes and
    `tool_used` frames purely for visibility.
  - `session_id`: chat session identifier (logging / dedupe).
  - `start` / `target`: optional WGS84 endpoints for the current trip, so
    mobility tools can fall back to known coordinates when the model
    omits explicit lat/lng arguments.
"""
import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext

from .action_enum import ActionEnum


@dataclass
class Coord:
    lat: float
    lon: float


@dataclass
class ChatDeps:
    event_queue: asyncio.Queue[str | None]
    session_id: str
    start: Coord | None = None
    target: Coord | None = None


def sse(event: str, data: dict[str, Any]) -> str:
    """Format a single Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _emit_frontend_action(
    ctx: RunContext[ChatDeps], action: ActionEnum, params: dict
) -> str:
    """Push a `frontend_action` SSE event for the browser to execute.

    Returns a `queued:<id>` token so the model sees a stable
    acknowledgement rather than `None`.
    """
    action_id = f"fa_{uuid.uuid4().hex[:8]}"
    await ctx.deps.event_queue.put(
        sse("frontend_action", {"id": action_id, "action": action.value, "params": params})
    )
    return f"queued:{action_id}"
