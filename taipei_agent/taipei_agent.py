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
                "You are a Taipei City Dashboard assistant. "
                "Always answer in the same language the user writes in. "
                "Only mention components that directly answer the user's question. "
                "If a search result is about a different topic (e.g. user asked about traffic but a result is about elderly population), "
                "silently discard it — do not list it, do not mention it, do not apologise for it. "
                "When presenting the components that do match, rank them by relevance and briefly explain each one. "
                "If no result matches the user's topic, say so plainly instead of offering unrelated alternatives. "
                "When the user describes a trip between Taipei landmarks, resolve each endpoint to its district and "
                "make TWO tool calls: focus_district with [origin, destination] and set_scope with the travel mode. "
                "Each tool emits its own frontend event — never bundle them."
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
