import asyncio

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import ModelMessage

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL, TWCC_LLAMA_FFM_MODEL
from tools.component import componenet_toolset
from tools.frontend import ChatDeps, frontend_toolset


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
            toolsets=[componenet_toolset, frontend_toolset],
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
