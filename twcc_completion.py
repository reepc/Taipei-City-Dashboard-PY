"""Example: call TWCC chat-completions API with pydantic-typed request/response.

Supports tool / function calling. The model decides whether to call a tool;
the response includes `choices[].message.tool_calls` when it does.
"""

import asyncio
import json
import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from config import TWCC_LLAMA_FFM_API_KEY, TWCC_LLAMA_FFM_API_URL, TWCC_LLAMA_FFM_MODEL
from observability import setup_logfire

setup_logfire()


TWCC_CHAT_URL = os.getenv(
    "TWCC_CHAT_URL",
    f"{(TWCC_LLAMA_FFM_API_URL or 'https://api-ams.twcc.ai/api/models').rstrip('/')}"
    "/chat/completions",
)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list["ToolCall"] | None = None


class FunctionSpec(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any]


class ToolSpec(BaseModel):
    type: Literal["function"] = "function"
    function: FunctionSpec


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    max_tokens: int = Field(default=500, gt=0)
    tools: list[ToolSpec] | None = None
    tool_choice: str | dict | None = None


class ToolCallFunction(BaseModel):
    name: str
    arguments: str

    def parsed_arguments(self) -> dict[str, Any]:
        return json.loads(self.arguments) if self.arguments else {}


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ChatChoiceMessage(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class ChatChoice(BaseModel):
    index: int | None = None
    message: ChatChoiceMessage
    finish_reason: str | None = None


class ChatUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    id: str | None = None
    object: str | None = None
    created: int | None = None
    model: str | None = None
    choices: list[ChatChoice] = Field(default_factory=list)
    usage: ChatUsage | None = None

    def tool_calls(self) -> list[ToolCall]:
        if not self.choices:
            return []
        return self.choices[0].message.tool_calls or []

    def text(self) -> str | None:
        if not self.choices:
            return None
        return self.choices[0].message.content


ChatMessage.model_rebuild()


async def chat(
    messages: list[ChatMessage] | list[dict],
    *,
    model: str = TWCC_LLAMA_FFM_MODEL,
    temperature: float = 0.5,
    max_tokens: int = 500,
    tools: list[ToolSpec] | list[dict] | None = None,
    tool_choice: str | dict | None = None,
    api_key: str | None = None,
    timeout: float = 60.0,
) -> ChatResponse:
    key = api_key or TWCC_LLAMA_FFM_API_KEY
    if not key:
        raise RuntimeError("TWCC_API_KEY not set in environment")

    typed_messages = [
        m if isinstance(m, ChatMessage) else ChatMessage.model_validate(m)
        for m in messages
    ]
    typed_tools: list[ToolSpec] | None = None
    if tools:
        typed_tools = [
            t if isinstance(t, ToolSpec) else ToolSpec.model_validate(t) for t in tools
        ]
    payload = ChatRequest(
        model=model,
        messages=typed_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=typed_tools,
        tool_choice=tool_choice,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            TWCC_CHAT_URL,
            headers=headers,
            json=payload.model_dump(exclude_none=True),
        )
        resp.raise_for_status()
        return ChatResponse.model_validate(resp.json())


# --- demo: tool calling round-trip ---

WEATHER_DB = {
    "Taipei": {"temp_c": 27, "condition": "cloudy"},
    "Tokyo": {"temp_c": 19, "condition": "sunny"},
}


def get_weather(city: str) -> dict:
    return WEATHER_DB.get(city, {"temp_c": 20, "condition": "unknown"})


WEATHER_TOOL = ToolSpec(
    function=FunctionSpec(
        name="get_weather",
        description="Get current weather for a city.",
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name in English"},
            },
            "required": ["city"],
        },
    )
)


async def main() -> None:
    messages: list[dict] = [
        {"role": "system", "content": "You are a helpful assistant. Use tools when needed."},
        {"role": "user", "content": "What's the weather in Taipei?"},
    ]

    print("=== round 1: ask model ===")
    r1 = await chat(messages, tools=[WEATHER_TOOL])
    print(r1.model_dump_json(indent=2, exclude_none=True))

    calls = r1.tool_calls()
    if not calls:
        print("\nModel did not call any tool. Reply:", r1.text())
        return

    print(f"\nModel called {len(calls)} tool(s):")
    for c in calls:
        print(f"  -> {c.function.name}({c.function.arguments})")

    # Append assistant's tool-call turn + each tool's result
    assistant_msg = r1.choices[0].message
    messages.append(
        {
            "role": "assistant",
            "content": assistant_msg.content or "",
            # tool_calls preserved via raw dict round-trip
        }
    )
    # Note: some servers require the assistant message to include tool_calls.
    # We rebuild it from the parsed response:
    messages[-1] = {
        "role": "assistant",
        "content": assistant_msg.content or "",
        "tool_calls": [c.model_dump() for c in calls],
    }

    for c in calls:
        result = get_weather(**c.function.parsed_arguments())
        messages.append(
            {
                "role": "tool",
                "tool_call_id": c.id,
                "name": c.function.name,
                "content": json.dumps(result),
            }
        )

    print("\n=== round 2: send tool results back ===")
    r2 = await chat(messages, tools=[WEATHER_TOOL])
    print("Reply:", r2.text())


if __name__ == "__main__":
    asyncio.run(main())
