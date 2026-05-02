"""Dashboard component lifecycle: discover → resolve to integer id → render.

A "component" is one card in the Taipei dashboard catalogue (an air-quality
chart, a parking-lot map layer, a population ranking, …). The catalogue is
the source of truth for what exists; the search endpoint is its semantic
index.

This toolset owns the entire flow:
  - `list_all_components` returns the full catalogue, including each
    component's INTEGER id and name. It's the single id-lookup tool.
  - `add_card_in_chat` renders a chosen id as a text/chart/table panel.
  - `add_map_component` renders the same id as a map layer.

Both render tools push the payload to the client via SSE *and* return it
to the model so the model can ground its reply in the actual values.
"""
import json

import httpx
from pydantic_ai import FunctionToolset, RunContext

from config import ALL_COMPONENTS_PATH, BACKEND_BASE_URL

from ._shared import ChatDeps, _emit_frontend_action
from .action_enum import ActionEnum


components_toolset: FunctionToolset[ChatDeps] = FunctionToolset(
    instructions=(
        "Workflow for dashboard-component questions (figures, rankings, "
        "geographic distributions — anything in the catalogue).\n"
        "\n"
        "1. RESOLVE TO INTEGER IDs.\n"
        "   - The canonical id table is in the system prompt — use those "
        "integers directly. Never invent an id.\n"
        "   - list_all_components() returns the full catalogue and exists "
        "only as a fallback for verifying the table. You should rarely "
        "need it.\n"
        "\n"
        "2. FILTER. Keep only candidates whose topic actually matches the user's "
        "question; do not trust similarity score alone. Drop near-misses silently "
        "rather than apologising. If nothing remains, say so plainly — do not fall "
        "back to unrelated components.\n"
        "\n"
        "3. RENDER each kept id with exactly one of:\n"
        "   - add_map_component(id) — map layer. Call this ONCE per geographic "
        "dataset the user is asking about. One call adds the whole layer "
        "(every parking lot, every YouBike station, every bike-lane segment) — "
        "do not loop over individual rows / sites. Pick this whenever the "
        "component represents places, routes, or regions the user would expect "
        "to see *on the map*:\n"
        "       • point datasets — 停車場 / parking lots, YouBike / 公共自行車 / "
        "Ubike, bus stops, EV chargers, accident or incident points;\n"
        "       • line datasets — 自行車道 / bike lanes, bus routes, road "
        "segments, MRT lines;\n"
        "       • polygon / choropleth — 行政區 distributions, land use, "
        "demographic density by district;\n"
        "       • heatmaps — 熱點, density of events.\n"
        "     Component names containing 位置, 點位, 分布, 熱點, 路網, 站點, "
        "or any place-type noun are almost always map components.\n"
        "   - add_card_in_chat(id) — text / chart / table panel. Use ONLY when "
        "the component is non-spatial: rankings, totals, time series, "
        "year-over-year comparisons, demographic figures.\n"
        "   Default to exactly one render tool per id. Render with BOTH only "
        "when the user is asking to *browse* the dataset itself — \"請給我 X 的"
        "停車場\", \"show me the YouBike stations near Y\", \"列出西門的充電樁\" — "
        "in which case add_map_component pins the layer on the map and "
        "add_card_in_chat surfaces the same dataset as a side panel. When a "
        "component could plausibly fit either render tool but the user is not "
        "browsing, prefer add_map_component.\n"
        "   Both accept INTEGER ids only — passing a topic string 400s. Both also "
        "return the payload to you for grounding."
    )
)


@components_toolset.tool_plain
def list_all_components() -> dict:
    """Return the full catalogue of dashboard components (metadata only).

    Source of truth for which components exist — do not assume one exists
    unless it appears here. Each entry carries an INTEGER component_id,
    name, and topic; that integer is what add_card_in_chat /
    add_map_component accept. The catalogue does NOT include per-component
    values — call add_card_in_chat or add_map_component on a chosen id to
    fetch the actual data.
    """
    return json.loads(ALL_COMPONENTS_PATH.read_text(encoding="utf-8"))


async def fetch_backend_data(component_id: int) -> dict:
    """Fetch the data for a component id from the backend."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_BASE_URL}/api/v1/agent/component/{component_id}"
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return {"error": "This component is currently unavailable."}


@components_toolset.tool
async def add_card_in_chat(
    ctx: RunContext[ChatDeps], component_id: int
) -> dict:
    """Render a component as a text / chart / table panel and return its data.

    One call serves both consumers: the frontend receives the payload via
    SSE (`params.data` on the `frontend_action` event with
    action="show_component") and renders the panel; the same payload is
    returned here so the model can quote concrete numbers.

    Use this for figures, rankings, anything text-shaped. For
    geographic values that belong on the map, use add_map_component.

    Args:
        component_id: Integer id from list_all_components (e.g. 214).
            Topic strings are rejected.
    """
    data = await fetch_backend_data(component_id)

    await _emit_frontend_action(
        ctx,
        ActionEnum.ADD_CARD_IN_CHAT,
        {"component_id": component_id, "data": data},
    )
    return data


@components_toolset.tool
async def add_map_component(
    ctx: RunContext[ChatDeps], component_id: int
) -> dict:
    """Render a component as a map layer and return its data.

    Call this ONCE per geographic dataset — a single call adds the entire
    layer (every parking lot, every YouBike station, the whole bike-lane
    network, the choropleth across all districts). Do not invoke this in
    a loop over individual sites or rows.

    Reach for this tool whenever the component is intrinsically spatial:
        • point datasets — parking lots / 停車場, YouBike / Ubike stations,
          bus stops, EV chargers, accident points;
        • line datasets — 自行車道 / bike lanes, bus routes, MRT lines;
        • polygon / choropleth — district-level distributions, land use;
        • heatmaps — incident density, 熱點.
    Component names containing 位置, 點位, 分布, 熱點, 路網, 站點, or any
    place-type noun almost always belong here.

    For non-spatial output (rankings, time series, totals) use
    add_card_in_chat instead. When in doubt for a geographic component,
    prefer this tool.

    Args:
        component_id: Integer id from list_all_components (e.g. 214).
            Topic strings are rejected.
    """
    data = await fetch_backend_data(component_id)

    await _emit_frontend_action(
        ctx,
        ActionEnum.ADD_COMPONENT,
        {"component_id": component_id, "data": data},
    )
    return data
