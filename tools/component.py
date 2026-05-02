import httpx
from pydantic_ai import FunctionToolset

from config import BACKEND_BASE_URL

componenet_toolset = FunctionToolset()


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
def get_component_data(component_id: str) -> dict:
    """Get detailed information and latest data for a specific dashboard component.

    Use this tool when the user wants to see the current data, charts, or details
    of a specific component identified by search_component.

    Args:
        component_id: The unique identifier of the dashboard component, as returned by search_component.
    """
    response = httpx.get(f"{BACKEND_BASE_URL}/api/v1/agent/component/{component_id}")
    response.raise_for_status()
    return response.json()