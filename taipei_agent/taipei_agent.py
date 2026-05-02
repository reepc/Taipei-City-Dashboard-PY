import asyncio

from pydantic_ai import Agent
from pydantic_ai.capabilities
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import ModelMessage

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL, TWCC_LLAMA_FFM_MODEL
from tools._shared import ChatDeps
from tools.components import components_toolset
from tools.mobility import mobility_toolset
from tools.places import places_toolset
from tools.ui import ui_toolset


class TaipeiAgent:
    def __init__(self) -> None:
        model = OpenAIChatModel(
            TWCC_LLAMA_FFM_MODEL,
            provider=OpenAIProvider(
                base_url=TWCC_LLAMA_FFM_API_URL,
                api_key=TWCC_LLAMA_FFM_API_KEY,
            ),
        )
        self.agent = Agent[ChatDeps, str](
            model=model,
            deps_type=ChatDeps,
            toolsets=[components_toolset, places_toolset, mobility_toolset, ui_toolset],
            system_prompt=(
                "You are the Taipei City Dashboard assistant.\n"
                "\n"
                "Style:\n"
                "- Reply in the same language the user wrote in.\n"
                "- When you surface components, rank them by relevance and give a one-line "
                "explanation of why each one matches before quoting key numbers from the data.\n"
                "- Silently drop search results that are off-topic — do not list them, do not "
                "apologise for them. If nothing matches the user's topic, say so plainly rather "
                "than offering unrelated alternatives.\n"
                "\n"
                "Map control (proactive):\n"
                "- When the user mentions a place, landmark, address, or district, drive the "
                "map for them — do not wait for words like \"zoom\" or \"pan\". \"帶我去 X\", "
                "\"show me X\", \"X 在哪\", \"我想看 X\", \"focus on X\" all imply a camera move.\n"
                "- Always call geocode_place first to get lat/lng — even for district names "
                "like \"信義區\" — then call goto_coordinate (default) or zoom_to_coordinate "
                "(for tight close-ups: \"放大到\", \"very focused\"). Never invent coordinates.\n"
                "- Pick zoom by scale: ~13 for a 區-level view, ~16 for a venue/address, "
                "~17–18 for a single building. Omit zoom for a pure pan.\n"
                "- Trip queries (\"從 A 到 B\"): focus the destination B only via "
                "goto_coordinate. Don't try to frame both ends.\n"
                "\n"
                "Grounding:\n"
                "- Every claim about dashboard data, parking, or POIs must come from a tool call "
                "you just made on this turn. Do not fabricate values and do not recall stale numbers.\n"
                "- If a tool returns an empty result or an error, tell the user instead of guessing."
            )
        )

    def chat(
        self,
        user_prompt: str,
        message_history: list[ModelMessage] | None = None,
        deps: ChatDeps | None = None,
    ):
        if deps is None:
            deps = ChatDeps(event_queue=asyncio.Queue(), session_id="sync")
        return self.agent.run_sync(
            user_prompt, message_history=message_history, deps=deps
        )

    def chat_stream(
        self,
        user_prompt: str,
        *,
        deps: ChatDeps,
        message_history: list[ModelMessage] | None = None,
    ):
        return self.agent.run_stream(
            user_prompt, deps=deps, message_history=message_history
        )
