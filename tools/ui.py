"""Direct map UI commands.

Tools here only push `frontend_action` SSE events; they do not fetch
data. Add a tool to this module when you need the agent to drive a
client-side map control (pan, zoom, layer toggle, …).
"""
import math

from pydantic_ai import FunctionToolset, RunContext

from ._shared import ChatDeps, _emit_frontend_action
from .action_enum import ActionEnum


ui_toolset: FunctionToolset[ChatDeps] = FunctionToolset(
    instructions=(
        "Direct map UI commands. Call these proactively whenever the user's "
        "request implies a map view change — do not wait for them to say "
        "\"zoom\" or \"pan\" literally. Phrases like 「帶我去 X」, 「show me X "
        "on the map」, 「X 在哪」, 「我想看 X」, 「focus on X」, 「附近有什麼」 "
        "all imply a camera move. If you only have a place name, "
        "geocode_place first, then call the right UI tool with the resolved "
        "lat/lng — never invent coordinates.\n"
        "\n"
        "Pick exactly ONE of the two tools below per request:\n"
        "\n"
        "goto_coordinate(lat, lng, zoom?) — pan the camera to a single point.\n"
        "  - Default tool for \"take me to X\", \"show me X on the map\", "
        "\"go to (lat, lng)\", and for district names (\"信義區\", \"大安區\") "
        "after geocoding. Pure pan when zoom is omitted; pass an explicit "
        "zoom when the user implies a scale change.\n"
        "  - Pick zoom by scale: ~13 for a 區-level view, ~16 for a venue or "
        "address (street level), ~17–18 for a single building.\n"
        "  - For trip queries (\"從 A 到 B\"), focus the destination B only "
        "with this tool. Don't try to frame both endpoints.\n"
        "  - Prefer this over zoom_to_coordinate unless the user explicitly "
        "wants a tight close-up.\n"
        "\n"
        "zoom_to_coordinate(lat, lng, radius_m=150) — tight bbox-fit on a "
        "point.\n"
        "  - Use when the user wants a \"very focused\" / \"close up\" / "
        "「放大到」 view of one venue, station, or address. The frontend "
        "fits the bbox corners to the screen edges.\n"
        "  - Raise radius_m to 300–500 for a block-scale view, lower to "
        "75–100 for a single building."
    )
)


@ui_toolset.tool
async def goto_coordinate(
    ctx: RunContext[ChatDeps],
    lat: float,
    lng: float,
    zoom: float | None = None,
) -> str:
    """Pan the map camera to a WGS84 coordinate, optionally setting zoom.

    Default tool for "take me to X" / "show me X on the map" once you
    have its lat/lng. Pure pan when `zoom` is omitted (the current zoom
    level is preserved); pass a Mapbox-style zoom (~14 neighbourhood,
    ~16 street, ~18 building) when the user also asked to zoom in.

    Args:
        lat: WGS84 latitude of the focus point.
        lng: WGS84 longitude of the focus point.
        zoom: Optional Mapbox-style zoom level (1-22). Omit to keep
            the current zoom; pass ~16 for a street-level close-up.
    """
    params: dict = {"center": {"lat": lat, "lng": lng}}
    if zoom is not None:
        params["zoom"] = zoom
    return await _emit_frontend_action(ctx, ActionEnum.GOTO, params)


@ui_toolset.tool
async def zoom_to_coordinate(
    ctx: RunContext[ChatDeps],
    lat: float,
    lng: float,
    radius_m: float = 150.0,
) -> str:
    """Zoom the map tightly onto a single WGS84 coordinate.

    Builds a `radius_m`-half-side bbox around (lat, lng) and emits a
    `zoom_to` frontend_action carrying both the centre and the bbox
    corners (sw / ne). The frontend fits its viewport so the bbox edges
    line up with the screen edges, giving a "very focused" view of the
    point.

    Args:
        lat: WGS84 latitude of the focus point.
        lng: WGS84 longitude of the focus point.
        radius_m: Half-side of the bbox in metres. Default 150 m for a
            tight single-venue close-up. Use 300–500 m for a
            block-scale view.
    """
    dlat = radius_m / 111_000.0
    dlng = radius_m / (111_000.0 * max(math.cos(math.radians(lat)), 1e-6))
    return await _emit_frontend_action(
        ctx,
        ActionEnum.ZOOM_TO,
        {
            "center": {"lat": lat, "lng": lng},
            "bbox": {
                "sw": {"lat": lat - dlat, "lng": lng - dlng},
                "ne": {"lat": lat + dlat, "lng": lng + dlng},
            },
            "radius_m": radius_m,
        },
    )
