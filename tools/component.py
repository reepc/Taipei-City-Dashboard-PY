import json

import httpx
from pydantic_ai import FunctionToolset

from config import BACKEND_BASE_URL, ALL_COMPONENTS_PATH


componenet_toolset = FunctionToolset(
    instructions=(
        "Workflow for dashboard data / component questions:\n"
        "1. RESOLVE TO NUMERIC IDs. Pick the right lookup tool:\n"
        "   - search_component_id(query) — topic-driven search "
        "(\"空氣品質\", \"交通壅塞\", \"population\", …).\n"
        "   - list_all_components() — full catalogue. Call this whenever the user asks "
        "for additional data, follow-ups like \"show me more\" / \"what else is there\", "
        "or any request that needs a component you have not already surfaced.\n"
        "2. FILTER. Keep only candidates whose topic actually matches the user's question — "
        "do not trust similarity score alone. If nothing remains, tell the user; do not fall "
        "back to unrelated components.\n"
        "3. SURFACE. For each kept id, call get_component_data (frontend toolset) with the "
        "INTEGER id. That single call renders the component for the user and returns its data "
        "to you for grounding. Never pass a topic string to get_component_data."
    )
)


@componenet_toolset.tool_plain
def search_component_id(
    query: str, limit: int = 10, score_threshold: float = 0.78
) -> dict:
    """Resolve a topic into NUMERIC component_ids ranked by similarity.

    The backend applies `limit` and `score_threshold` server-side. Each
    result carries an integer `component_id` — that integer (not the topic
    string) is what you feed to get_component_data.

    Args:
        query: Natural language description of the topic, in Chinese or English.
            Examples: "交通壅塞", "空氣品質", "老人 高齡 長照", "population".
            Multiple keywords can be space-separated to broaden the search.
        limit: Maximum number of component_ids to return. 1–30.
        score_threshold: Minimum similarity score to keep. Range [0, 1].
            Raise above 0.85 for only highly relevant components.
    """
    response = httpx.post(
        f"{BACKEND_BASE_URL}/api/v1/agent/search",
        json={"query": query, "limit": limit, "score": score_threshold},
    )
    response.raise_for_status()
    return response.json()


@componenet_toolset.tool_plain
def list_all_components() -> dict:
    """Return the full catalogue of dashboard components (metadata only).

    Source of truth for which components exist — do not assume a component
    exists unless it appears here or in a search_component_id result. The
    catalogue carries name and topic, NOT the per-component values; call
    get_component_data on a chosen id to fetch actual data.
    """
    return json.loads(ALL_COMPONENTS_PATH.read_text(encoding="utf-8"))
