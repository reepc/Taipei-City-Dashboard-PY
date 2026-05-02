"""Frontend-facing tools for the chat endpoint.

The tools share `ChatDeps`, which carries the per-request SSE queue. UI
action tools (focus_district, open_dashboard, toggle_layer) push
`frontend_action` events the client executes; data lookups push
`tool_used` events for visibility.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import FunctionToolset, RunContext


TravelMode = Literal["biking", "driving", "walking", "public_transport"]


@dataclass
class ChatDeps:
    event_queue: asyncio.Queue[str | None]
    session_id: str


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


frontend_toolset: FunctionToolset[ChatDeps] = FunctionToolset(
    instructions=(
        "Use these tools to control the Taipei City Dashboard UI or look up "
        "quick district/dataset info. "
        "Call focus_district whenever the user asks to focus a district OR "
        "describes a trip — pass a single-element list for a plain focus, "
        "or [origin_district, destination_district] in route order for a trip. "
        "When the user describes a trip between Taipei landmarks (e.g. "
        "'from Taipei City Hall to Ximen'), make TWO tool calls: "
        "(1) focus_district with the resolved [origin, destination] districts "
        "(市政府→信義區, 西門→萬華區, etc.); "
        "(2) set_scope with the travel mode "
        "(biking / driving / walking / public_transport — public_transport "
        "covers BUS and MRT). "
        "These emit two separate frontend events — do not try to bundle them. "
        "Use open_dashboard and toggle_layer for the matching UI actions."
    )
)


@frontend_toolset.tool
async def get_district_stats(ctx: RunContext[ChatDeps], district: str) -> dict:
    """Return mock population and area stats for a Taipei district."""
    data = {
        "信義區": {"population": 217000, "area_km2": 11.2},
        "大安區": {"population": 308000, "area_km2": 11.4},
        "中正區": {"population": 159000, "area_km2": 7.6},
    }.get(district, {"population": 0, "area_km2": 0})
    await ctx.deps.event_queue.put(
        sse("tool_used", {"name": "get_district_stats", "args": {"district": district}})
    )
    return data


async def _emit_frontend_action(
    ctx: RunContext[ChatDeps], action: str, params: dict
) -> str:
    action_id = f"fa_{uuid.uuid4().hex[:8]}"
    await ctx.deps.event_queue.put(
        sse("frontend_action", {"id": action_id, "action": action, "params": params})
    )
    return f"queued:{action_id}"


@frontend_toolset.tool
async def focus_district(ctx: RunContext[ChatDeps], districts: list[str]) -> str:
    """Pan/zoom the map to focus on one or more Taipei districts.

    For a trip query, pass [origin_district, destination_district] in route
    order. For a plain focus request, pass a single-element list.

    Args:
        districts: Ordered list of Taipei districts to focus. Use the official
            Chinese name with the 區 suffix (e.g. "信義區", "萬華區").
    """
    return await _emit_frontend_action(
        ctx, "focus_district", {"districts": districts}
    )


@frontend_toolset.tool
async def set_scope(ctx: RunContext[ChatDeps], mode: TravelMode) -> str:
    """Set the travel mode for a trip the user described.

    Call this together with focus_district when the user describes a trip
    between Taipei landmarks.

    Args:
        mode: Travel mode — one of "biking", "driving", "walking",
            "public_transport". Use "public_transport" for any BUS / MRT trip.
    """
    return await _emit_frontend_action(ctx, "set_scope", {"mode": mode})


@frontend_toolset.tool
async def open_dashboard(ctx: RunContext[ChatDeps], dashboard_id: str) -> str:
    """Open a named dashboard panel in the UI."""
    return await _emit_frontend_action(ctx, "open_dashboard", {"dashboard_id": dashboard_id})


@frontend_toolset.tool
async def toggle_layer(ctx: RunContext[ChatDeps], layer: str, visible: bool) -> str:
    """Show or hide a map overlay layer."""
    return await _emit_frontend_action(
        ctx, "toggle_layer", {"layer": layer, "visible": visible}
    )
