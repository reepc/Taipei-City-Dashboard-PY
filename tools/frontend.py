"""Frontend-facing tools for the chat endpoint.

The tools share `ChatDeps`, which carries the per-request SSE queue. UI
action tools (focus_district, open_dashboard, toggle_layer) push
`frontend_action` events the client executes; data lookups push
`tool_used` events for visibility.
"""
import asyncio
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic_ai import FunctionToolset, RunContext

from config import BACKEND_BASE_URL

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
        "These tools drive the UI (each call emits its own SSE event — never bundle "
        "them) and look up live data.\n"
        "\n"
        "Component rendering:\n"
        "- get_component_data(component_id: int) is the only way to put a dashboard "
        "component on the user's screen. The id MUST be the integer returned by "
        "search_component_id or list_all_components — passing a topic string 400s. "
        "The same call also returns the payload to you for grounding.\n"
        "\n"
        "Trip workflow (user describes travel between Taipei landmarks, e.g. "
        "'from Taipei City Hall to Ximen'):\n"
        "1. Resolve each endpoint to its Taipei district "
        "(市政府→信義區, 西門→萬華區, …).\n"
        "2. focus_district([origin, destination]).\n"
        "3. set_scope(mode) — biking | driving | walking | public_transport "
        "(public_transport covers BUS and MRT).\n"
        "4. request_map_info(mode) — fetches the POIs for that mode.\n"
        "5. DRIVING only: also call get_parking_availability. If occupied_rate_avg "
        "≥ 0.9 with healthy realtime coverage (with_realtime / total_lots ≳ 0.3), "
        "warn the user parking is likely full and consider suggesting "
        "public_transport instead.\n"
        "\n"
        "Plain focus (no trip): focus_district([single_district]) on its own.\n"
        "\n"
        "Direct UI commands: open_dashboard / toggle_layer — use when the user asks "
        "for those actions by name."
    )
)


@frontend_toolset.tool
async def get_component_data(
    ctx: RunContext[ChatDeps], component_id: int
) -> dict:
    """Fetch a dashboard component's data, render it for the user, and return it.

    One call serves both consumers: the frontend receives the payload via
    SSE (params.data on the frontend_action event) and renders the
    component, while the same payload is returned here for grounding.

    Args:
        component_id: Integer component id from search_component_id or
            list_all_components (e.g. 214). Topic strings are rejected.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BACKEND_BASE_URL}/api/v1/agent/component/{component_id}"
        )
        response.raise_for_status()
        data = response.json()
    await _emit_frontend_action(
        ctx,
        ActionEnum.SHOW_COMPONENT,
        {"component_id": component_id, "data": data},
    )
    return data


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
async def get_parking_availability(
    ctx: RunContext[ChatDeps],
    lat: float | None = None,
    lng: float | None = None,
    radius_m: float = 500.0,
) -> dict:
    """Aggregate parking-lot occupancy in a bbox around a destination.

    POSTs a `radius_m`-half-side bbox around (lat, lng) — or around
    ctx.deps.target if lat/lng are omitted — to /api/v1/agent/parking-bbox.
    Returns an empty dict when no coordinates are available.

    Response (key fields under `data`):
      - total_lots, with_realtime — counts inside the bbox.
      - occupied_rate_avg — 0..1 average. Lots with no realtime feed are
        counted as fully occupied (1.0); divide with_realtime / total_lots
        to gauge how much of the average is real signal vs. fallback.
      - by_city[] — same fields split into taipei / newtaipei.

    Args:
        lat: WGS84 latitude of the search centre. Omit to use target.
        lng: WGS84 longitude of the search centre. Omit to use target.
        radius_m: Half-side of the search square in metres. 500 fits a
            downtown block; raise to 1000–2000 for suburbs.
    """
    if lat is None or lng is None:
        if ctx.deps.target is None:
            await ctx.deps.event_queue.put(
                sse(
                    "tool_used",
                    {
                        "name": "get_parking_availability",
                        "note": "no coordinates supplied",
                    },
                )
            )
            return {}
        lat = ctx.deps.target.lat
        lng = ctx.deps.target.lon

    dlat = radius_m / 111_000.0
    dlng = radius_m / (111_000.0 * max(math.cos(math.radians(lat)), 1e-6))
    bbox = {
        "lat_min": lat - dlat,
        "lat_max": lat + dlat,
        "lng_min": lng - dlng,
        "lng_max": lng + dlng,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BACKEND_BASE_URL}/api/v1/agent/parking-bbox",
            json=bbox,
        )
        response.raise_for_status()
        return response.json()


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
