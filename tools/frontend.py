"""Frontend-facing tools for the chat endpoint.

The tools share `ChatDeps`, which carries the per-request SSE queue. UI
action tools (focus_district, open_dashboard, toggle_layer) push
`frontend_action` events the client executes; data lookups push
`tool_used` events for visibility.
"""
import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai import FunctionToolset, RunContext

from .action_enum import ActionEnum


TravelMode = Literal["biking", "driving", "walking", "public_transport"]


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
        "After set_scope, call request_map_info with the same mode to fetch "
        "the POIs the user needs along the trip (Ubike stations for biking, "
        "parking lots for driving, MRT/bus stations for public_transport). "
        "The tool reads the start/target coordinates supplied by the frontend "
        "and emits a third map_info event with the POI list. "
        "Use open_dashboard and toggle_layer for the matching UI actions."
    )
)


@frontend_toolset.tool
async def show_component_by_id(ctx: RunContext[ChatDeps], component_id: str) -> str:
    """Open a dashboard component by its unique ID."""
    return await _emit_frontend_action(
        ctx, ActionEnum.SHOW_COMPONENT_BY_ID, {"component_id": 214} #! Change to real id 
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
    ctx: RunContext[ChatDeps], action: ActionEnum, params: dict
) -> str:
    action_id = f"fa_{uuid.uuid4().hex[:8]}"
    await ctx.deps.event_queue.put(
        sse("frontend_action", {"id": action_id, "action": action.value, "params": params})
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
        ctx, ActionEnum.FOCUS_DISTRICT, {"districts": districts}
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
    return await _emit_frontend_action(ctx, ActionEnum.SET_SCOPE, {"mode": mode})


def _mock_map_info(mode: TravelMode, start: Coord, target: Coord) -> list[dict]:
    """Stand-in POI lookup. Swap in real Ubike / parking / transit APIs later."""
    if mode == "biking":
        return [
            {"kind": "ubike", "label": "起點 Ubike 站", "lat": start.lat, "lon": start.lon},
            {"kind": "ubike", "label": "終點 Ubike 站", "lat": target.lat, "lon": target.lon},
        ]
    if mode == "driving":
        return [
            {"kind": "parking", "label": "起點停車場", "lat": start.lat, "lon": start.lon},
            {"kind": "parking", "label": "終點停車場", "lat": target.lat, "lon": target.lon},
        ]
    if mode == "public_transport":
        return [
            {"kind": "mrt", "label": "起點 MRT 站", "lat": start.lat, "lon": start.lon},
            {"kind": "mrt", "label": "終點 MRT 站", "lat": target.lat, "lon": target.lon},
        ]
    return []  # walking has no associated POIs for now


@frontend_toolset.tool
async def request_map_info(
    ctx: RunContext[ChatDeps], mode: TravelMode
) -> list[dict]:
    """Fetch POIs the user needs along the trip, based on travel mode.

    Reads start/target coordinates the frontend supplied with the request:
      - biking            → Ubike stations near origin and destination
      - driving           → parking lots near origin and destination
      - public_transport  → MRT / bus stations
      - walking           → no POIs

    Call this AFTER focus_district and set_scope, with the same mode you
    passed to set_scope. Returns an empty list if start/target coordinates
    were not supplied.
    """
    if ctx.deps.start is None or ctx.deps.target is None:
        await ctx.deps.event_queue.put(
            sse(
                "tool_used",
                {
                    "name": "request_map_info",
                    "args": {"mode": mode},
                    "note": "no coordinates supplied",
                },
            )
        )
        return []
    pois = _mock_map_info(mode, ctx.deps.start, ctx.deps.target)
    await _emit_frontend_action(ctx, ActionEnum.REQUEST_MAP_INFO, {"mode": mode, "pois": pois})
    return pois


@frontend_toolset.tool
async def open_dashboard(ctx: RunContext[ChatDeps], dashboard_id: str) -> str:
    """Open a named dashboard panel in the UI."""
    return await _emit_frontend_action(ctx, ActionEnum.OPEN_DASHBOARD, {"dashboard_id": dashboard_id})


@frontend_toolset.tool
async def toggle_layer(ctx: RunContext[ChatDeps], layer: str, visible: bool) -> str:
    """Show or hide a map overlay layer."""
    return await _emit_frontend_action(
        ctx, ActionEnum.TOGGLE_LAYER, {"layer": layer, "visible": visible}
    )
