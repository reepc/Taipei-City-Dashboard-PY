"""Routing for Taipei trips.

Single tool:
  - `navigate` — actual route plan, rendered as a map layer through the
    same dashboard-component envelope as any other geographic component.

Per-mode infrastructure (parking lots, YouBike stations, pavements) is
surfaced by turning on the matching catalogue layer via
add_map_component, not by fetching aggregate availability here.
"""
from datetime import date, datetime, timezone
from typing import Literal

import httpx
from pydantic_ai import FunctionToolset, RunContext

from config import BACKEND_BASE_URL, NAVIGATE_BASE_URL

from ._shared import ChatDeps, _emit_frontend_action, sse
from .action_enum import ActionEnum


TravelMode = Literal["biking", "driving", "walking", "public_transport"]


mobility_toolset: FunctionToolset[ChatDeps] = FunctionToolset(
    instructions=(
        "Trip routing for Taipei (user describes travel between landmarks, "
        "e.g. \"from Taipei City Hall to Ximen\").\n"
        "\n"
        "1. Resolve the destination to lat/lng with geocode_place (and origin "
        "too — navigate needs both). Focus the map on the destination with "
        "goto_coordinate(dest_lat, dest_lng, zoom=14) — neighbourhood level so "
        "the surrounding infrastructure is visible. Don't try to frame the "
        "origin.\n"
        "2. Turn on the mode-specific map layer via add_map_component using "
        "the canonical id: driving → 4 (公共停車場), YouBike → 60 "
        "(YouBike使用情況), walking → 9 (人行道). These are the only valid "
        "ids — never invent one. This is how parking / station / pavement "
        "context reaches the user; the agent does not fetch per-place "
        "availability.\n"
        "3. Call navigate(...) to plan the route. It needs WGS84 coordinates; "
        "if you only have place names, geocode_place first and feed lat/lng "
        "in. Never invent coordinates."
    )
)


_NAVIGATE_API_MODE = {
    "driving": "car",
    "biking": "biking",
    "walking": "pedestrian",
    "public_transport": "public_transport",
}

# Synthesised id for the route layer. The frontend's add_component handler
# uses component_id to dedupe / overwrite, so a fixed sentinel keeps each
# new route replacing the previous one rather than stacking layers.
_ROUTE_INDEX = "navigate_route"

_MODE_LABEL_ZH = {
    "car": "開車",
    "biking": "騎乘",
    "pedestrian": "步行",
    "public_transport": "大眾運輸",
}


def _build_route_component_envelope(
    route_fc: dict,
    api_mode: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> dict:
    """Wrap a /api/navigate FeatureCollection in the dashboard-component envelope.

    Mirrors the `component` block returned by /api/v1/agent/component/{id}
    so the frontend's `add_component` handler can render the route through
    the same map_config pipeline as any other geojson layer — no dedicated
    route handler needed. The caller wraps this in
    {component, query_type, status} to match the canonical
    `params.data` schema.
    """
    summary = {}
    for feat in route_fc.get("features", []):
        props = feat.get("properties") or {}
        if "kind" not in props:  # the overall route feature
            summary = props
            break
    label = _MODE_LABEL_ZH.get(api_mode, api_mode)
    olon, olat = origin
    dlon, dlat = destination
    short_desc = (
        f"{label}路線：({olon:.5f}, {olat:.5f}) → ({dlon:.5f}, {dlat:.5f})"
    )
    if summary:
        dist_km = (summary.get("distance_m") or 0) / 1000
        dur_min = (summary.get("duration_s") or 0) / 60
        short_desc += f"，約 {dist_km:.1f} km / {dur_min:.0f} 分鐘"

    properties = [
        {"key": "instruction", "name": "指示"},
        {"key": "name", "name": "路名"},
        {"key": "distance_m", "name": "距離(公尺)"},
        {"key": "duration_s", "name": "時間(秒)"},
        {"key": "mode", "name": "交通方式"},
    ]
    if api_mode == "pedestrian":
        properties.append({"key": "pavement_ratio", "name": "人行道比例"})

    return {
        "id": datetime.now(timezone.utc).isoformat(),  # unique id for this route
        "index": _ROUTE_INDEX,
        "name": "導航路線",
        "chart_data": [
            {
                "name": "導航路線",
                "type": "fill",
                "icon": "",
                "value": 0
            }
        ],
        "chart_config": {
            "index": "parking",
            "color": [
                "#FF6B35"
            ],
            "types": [
                "MapLegend"
            ],
            "unit": "parking"
        },
        "history_config": None,
        "map_config": [
            {
                "id": datetime.now(timezone.utc).isoformat(),
                "city": "taipei",
                "data": route_fc,
                "index": _ROUTE_INDEX,
                "title": "導航路線",
                "type": "line",
                "source": "geojson",
                "size": None,
                "icon": None,
                "paint": {
                    "line-color": "#FF6B35",
                    "line-width": 4,
                },
                "property": properties,
            }
        ],
        "map_filter": None,
        "time_from": "static",
        "time_to": None,
        "update_freq": None,
        "update_freq_unit": "",
        "source": f"navigate ({api_mode})",
        "short_desc": short_desc,
        "long_desc": "",
        "use_case": "",
        "links": [],
        "contributors": [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "query_type": "static",
        "city": "taipei",
    }


@mobility_toolset.tool
async def navigate(
    ctx: RunContext[ChatDeps],
    origin_lng: float,
    origin_lat: float,
    destination_lng: float,
    destination_lat: float,
    mode: TravelMode = "driving",
    avoid_obstacles: bool = False,
) -> dict:
    """Plan a route between two WGS84 coordinates and render it on the map.

    Use this when the user wants directions / a route between two
    specific places in Taipei. This tool only accepts coordinates; if
    the user gave a place name and you don't know its lat/lng, call
    geocode_place first and feed `lat` / `lng` from its result here.
    Never invent coordinates.

    Coordinates are WGS84 longitude/latitude pairs. Example: Zhongxiao
    Fuxing Station east side ≈ (lng=121.5430, lat=25.0418).

    Mode defaults to "driving" when the user did not say how they are
    travelling. `avoid_obstacles=True` (default) routes around closed
    roads via /api/navigate-avoid; that endpoint does not support
    "public_transport", so this tool transparently falls back to
    /api/navigate when mode="public_transport".

    Walking routes are sidewalk-aware: each line segment carries a
    `pavement_ratio` property (0..1, share of that road covered by
    proper pavement). Taipei sidewalks are notoriously inconsistent, so
    surface this to the user when low ratios show up on their route.

    The route GeoJSON is wrapped in the standard dashboard-component
    envelope (route inlined in map_config[0].data) and pushed via the
    `add_component` SSE action, so the frontend renders it through the
    same map-layer pipeline as any other component.

    Args:
        origin_lng: Origin longitude (WGS84). e.g. 121.5430.
        origin_lat: Origin latitude (WGS84). e.g. 25.0418.
        destination_lng: Destination longitude (WGS84).
        destination_lat: Destination latitude (WGS84).
        mode: "driving" (default), "biking", "walking", or
            "public_transport".
        avoid_obstacles: Route around obstacles. Default True. Ignored
            (forced False) when mode="public_transport".
    """
    use_avoid = avoid_obstacles and mode != "public_transport"
    path = "/api/navigate-avoid" if use_avoid else "/api/navigate"
    api_mode = _NAVIGATE_API_MODE[mode]
    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{destination_lng},{destination_lat}",
        "mode": api_mode,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{NAVIGATE_BASE_URL}{path}", params=params)
        response.raise_for_status()
        data = response.json()

    envelope = _build_route_component_envelope(
        data,
        api_mode,
        (origin_lng, origin_lat),
        (destination_lng, destination_lat),
    )
    await _emit_frontend_action(
        ctx,
        ActionEnum.ADD_COMPONENT,
        {
            "component_id": datetime.now(timezone.utc).isoformat(),
            "data": {
                "component": envelope,
                "query_type": "static",
                "status": "success",
            },
        },
    )
    return data
