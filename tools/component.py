import json

import httpx
from pydantic_ai import FunctionToolset

from config import BACKEND_BASE_URL, ALL_COMPONENTS_PATH


componenet_toolset = FunctionToolset(
    instructions=(
        "When the user asks about data or components on the Taipei City Dashboard, follow these steps:\n"
        "1. Call search_component to find candidates.\n"
        "2. Filter the search results to only those whose topic matches the user's question. "
        "Drop any result that is about a different subject, even if its similarity score is above the threshold. "
        "If filtering leaves zero results, tell the user no matching component was found — do NOT fall back to unrelated ones.\n"
        "3. For every component you decided to surface, call get_component_data (frontend toolset) with its "
        "component_id. That single call fetches the component's payload, ships it to the frontend over SSE so "
        "the page renders, AND returns the same payload to you — use the returned numbers to ground your reply.\n"
        "Present each kept component as: name — explanation of why it's relevant, followed by key details "
        "from the returned data.\n"
        "If the user asks what components are available or wants a full list, call list_all_components."
    )
)


@componenet_toolset.tool_plain
def search_component(query: str, limit: int = 10, score_threshold: float = 0.78) -> dict:
    """Search dashboard components by natural language query.

    Use this tool when the user asks about available data, charts, or visualisations
    on the Taipei City Dashboard (e.g. traffic, population, air quality).
    Returns components ranked by semantic similarity; higher score means more relevant.

    Args:
        query: Natural language description of the data topic, in Chinese or English.
            Examples: "交通壅塞", "空氣品質", "老人 高齡 長照", "population distribution".
            Multiple keywords can be space-separated to broaden the search.
        limit: Maximum number of components to return. Must be between 1 and 30.
        score_threshold: Minimum similarity score to include a result. Range [0, 1].
            Lower values return more (but less relevant) results.
            Raise this above 0.85 when you need only highly relevant components.
    """
    response = httpx.post(
        f"{BACKEND_BASE_URL}/api/v1/agent/search",
        json={"query": query, "limit": limit, "score": score_threshold},
    )
    response.raise_for_status()
    return response.json()


@componenet_toolset.tool_plain
def list_all_components() -> dict:
    """List all available components on the Taipei City Dashboard.

    Use this tool when the user asks what components or data sources are available,
    wants a full catalogue, or needs to browse by category.
    """
    return json.loads(ALL_COMPONENTS_PATH.read_text(encoding="utf-8"))
