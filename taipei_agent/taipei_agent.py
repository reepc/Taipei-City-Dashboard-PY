from pydantic_ai import Agent
from pydantic_ai.capabilities import Thinking

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL


class TaipeiAgent:
    def __init__(self) -> None:
        model = OpenAIChatModel(
            "TWCC_LLAMA_FFM",
            provider=OpenAIProvider(
                base_url=TWCC_LLAMA_FFM_API_URL,
                api_key=TWCC_LLAMA_FFM_API_KEY,
            )
        )
        self.agent = Agent(
            model=model,
        )

    async def chat(self, messages: list):
        response = await self.agent.run(messages)
        return response