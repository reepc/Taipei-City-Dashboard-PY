from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import ModelMessage

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL, TWCC_LLAMA_FFM_MODEL


class TaipeiAgent:
    def __init__(self) -> None:
        model = OpenAIChatModel(
            TWCC_LLAMA_FFM_MODEL,
            provider=OpenAIProvider(
                base_url=TWCC_LLAMA_FFM_API_URL,
                api_key=TWCC_LLAMA_FFM_API_KEY,
            )
        )
        self.agent = Agent(model=model)

    def chat(
        self,
        user_prompt: str,
        message_history: list[ModelMessage] | None = None,
    ):
        result = self.agent.run_sync(user_prompt, message_history=message_history)
        return result