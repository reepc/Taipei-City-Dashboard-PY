"""Direct map UI commands.

Tools here only push `frontend_action` SSE events; they do not fetch
data. Add a tool to this module when you need the agent to drive a
client-side map control (pan, zoom, layer toggle, …).
"""
from pydantic_ai import FunctionToolset, RunContext

from ._shared import ChatDeps, _emit_frontend_action
from .action_enum import ActionEnum


ui_toolset: FunctionToolset[ChatDeps] = FunctionToolset(
    instructions=(
        "Direct map UI commands.\n"
        "\n"
        "focus_district([districts]) pans/zooms the map to one or more Taipei "
        "districts.\n"
        "  - Trip query: pass [origin_district, destination_district] in route "
        "order so both ends are in view.\n"
        "  - Plain focus request (\"show me 大安區\"): pass a single-element list."
    )
)


@ui_toolset.tool
async def focus_district(ctx: RunContext[ChatDeps], districts: list[str]) -> str:
    """Pan/zoom the map to focus on one or more Taipei districts.

    Args:
        districts: Ordered list of Taipei districts to focus. Use the
            official Chinese name with the 區 suffix
            (e.g. "信義區", "萬華區"). For a trip, pass
            [origin_district, destination_district] in route order.
    """
    return await _emit_frontend_action(
        ctx, ActionEnum.FOCUS_DISTRICT, {"districts": districts}
    )
