"""Place-name resolution: free-form Taipei query → WGS84 lat/lng + 區."""
from pydantic_ai import FunctionToolset, RunContext

from ._shared import ChatDeps, sse
from .geocode_ral_addresses import async_resolve_place


places_toolset: FunctionToolset[ChatDeps] = FunctionToolset(
    instructions=(
        "Place-name resolution.\n"
        "\n"
        "geocode_place(query) turns a Taipei landmark or address "
        "(\"台北101\", \"信義威秀\", \"中正區忠孝東路一段1號\") into WGS84 lat/lng "
        "plus the matching 區. Call this whenever you need coordinates for a place "
        "described in natural language and don't already know exact lat/lng — "
        "typically before navigate(...), before driving the map with "
        "goto_coordinate / zoom_to_coordinate, or before passing a centre to "
        "get_parking_availability / get_youbike_availability.\n"
        "\n"
        "Never invent coordinates — geocode or ask the user."
    )
)


@places_toolset.tool
async def geocode_place(ctx: RunContext[ChatDeps], query: str) -> dict:
    """Resolve a Taipei place name or address to WGS84 lat/lng + district.

    Address-style inputs ("中正區忠孝東路一段1號") are normalised before
    the lookup; landmark / POI inputs ("台北101", "信義威秀") fall back
    to a Taipei-biased POI search.

    Args:
        query: Free-form place name or address. Chinese or English; the
            "臺北市" / "台北市" prefix is optional.

    Returns:
        On hit: {"lat": ..., "lng": ..., "name": ..., "road": ...,
                 "district": ...}.
        On miss: {"found": False, "query": ...} — ask the user to
        clarify rather than guessing coordinates.
    """
    await ctx.deps.event_queue.put(
        sse("tool_used", {"name": "geocode_place", "args": {"query": query}})
    )
    try:
        result = await async_resolve_place(query)
    except Exception as e:
        return {"found": False, "query": query, "error": repr(e)}
    if not result:
        return {"found": False, "query": query}
    return {
        "lat": result["lat"],
        "lng": result["lon"],
        "name": result.get("name"),
        "road": result.get("road"),
        "district": result.get("district"),
    }
