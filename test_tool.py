"""Test pydantic-ai Agent with tool calling against TWCC chat endpoint."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL, TWCC_LLAMA_FFM_MODEL
from observability import setup_logfire

setup_logfire()


def build_agent() -> Agent:
    model = OpenAIChatModel(
        TWCC_LLAMA_FFM_MODEL,
        provider=OpenAIProvider(
            base_url=TWCC_LLAMA_FFM_API_URL,
            api_key=TWCC_LLAMA_FFM_API_KEY,
        ),
    )
    agent = Agent(
        model=model,
        system_prompt=(
            "You are a helpful assistant. "
            "When user asks about current time or weather, "
            "you MUST call the provided tools instead of guessing."
        ),
    )

    @agent.tool_plain
    def get_current_time(timezone: str = "Asia/Taipei") -> str:
        """Return current local time in given IANA timezone (e.g. 'Asia/Taipei')."""
        now = datetime.now(ZoneInfo(timezone))
        return now.isoformat(timespec="seconds")

    @agent.tool_plain
    def get_weather(city: str) -> dict:
        """Return current weather for a city. (Mocked data for testing.)"""
        fake = {
            "Taipei": {"temp_c": 27, "condition": "cloudy", "humidity": 78},
            "Tokyo": {"temp_c": 19, "condition": "sunny", "humidity": 55},
            "New York": {"temp_c": 12, "condition": "rainy", "humidity": 88},
        }
        return fake.get(city, {"temp_c": 20, "condition": "unknown", "humidity": 60})

    return agent


def print_new_tool_trace(result) -> None:
    print("\n--- new tool calls this turn ---")
    for msg in result.new_messages():
        for part in getattr(msg, "parts", []):
            kind = type(part).__name__
            if kind == "ToolCallPart":
                print(f"  -> {part.tool_name}({part.args})")
            elif kind == "ToolReturnPart":
                print(f"  <- {part.tool_name} = {part.content}")


async def test_tool_call_session() -> None:
    """Single session: pass message_history forward so model has context."""
    agent = build_agent()
    history: list = []

    turns = [
        "台北現在幾點?",
        "那天氣呢?",
        "跟東京比的話?",
    ]

    for i, q in enumerate(turns, 1):
        print(f"\n=== Turn {i}: {q} ===")
        result = await agent.run(q, message_history=history)
        print(result.output)
        print_new_tool_trace(result)
        history = result.all_messages()

    print(f"\n--- session summary: {len(history)} messages retained ---")


if __name__ == "__main__":
    asyncio.run(test_tool_call_session())
