import json

import httpx
from pydantic_ai import FunctionToolset

from config import BACKEND_BASE_URL, ALL_COMPONENTS_PATH


componenet_toolset = FunctionToolset(
    instructions=(
        "When the user asks about data or components on the Taipei City Dashboard, follow these steps:\n"
        "1. Call search_component_id with a topic query — it returns a ranked list of candidate component_ids.\n"
        "2. Filter the search results to only those whose topic matches the user's question. "
        "Drop any result that is about a different subject, even if its similarity score is above the threshold. "
        "If filtering leaves zero results, tell the user no matching component was found — do NOT fall back to unrelated ones.\n"
        "3. For every component_id you decided to surface, call get_component_data (frontend toolset) with that "
        "component_id. That single call fetches the component's payload, ships it to the frontend over SSE so "
        "the page renders, AND returns the same payload to you — use the returned numbers to ground your reply.\n"
        "Present each kept component as: name — explanation of why it's relevant, followed by key details "
        "from the returned data.\n"
        "Call list_all_components every time the user asks for additional data — follow-ups like "
        "'show me more', 'what else is there', or any new request that needs a component you haven't "
        "already surfaced. It is also the right tool when the user explicitly asks what components or "
        "data sources are available. Use the catalogue to pick the right component_ids before fetching data."
    )
)


@componenet_toolset.tool_plain
def search_component_id(
    query: str, limit: int = 10, score_threshold: float = 0.78
) -> dict:
    """Resolve a topic into NUMERIC component_ids you can pass to get_component_data.

    Always call this BEFORE get_component_data when you only have a topic
    (e.g. "空氣品質", "交通壅塞") and not yet a numeric id. The backend ranks
    by semantic similarity and applies `limit` and `score_threshold`
    server-side. Each result includes an integer `component_id` — that
    integer is what you pass to get_component_data.

    Do NOT pass topic strings to get_component_data; they will fail with 400.

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
    """Return the full catalogue of dashboard components (name + topic, no data).

    CALL THIS EVERY TIME the user asks for additional data — including:
      - any request that needs a component you haven't already surfaced,
      - follow-ups like "show me more", "what else is there", "any other …",
      - open-ended browse queries, or
      - explicit catalogue / "what components are available" questions.

    The returned catalogue lets you pick the right component_ids before
    calling get_component_data. Use it as the source of truth for what
    exists; do not assume a component exists without seeing it here or in a
    search_component_id result.

    The catalogue contains metadata only (no per-component values) — fetch
    actual data via get_component_data once you've chosen the component_ids.
    """
    return json.loads(ALL_COMPONENTS_PATH.read_text(encoding="utf-8"))
