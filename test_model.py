from pydantic_ai.messages import ModelResponse, ToolReturn

from taipei_agent.taipei_agent import TaipeiAgent


def print_tool_activity(result):
    for msg in result.all_messages():
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if hasattr(part, "tool_name"):
                    print(f"[tool call] {part.tool_name}({part.args})")
        elif isinstance(msg, ToolReturn):
            print(f"[tool result] {msg.content}")


def test_taipei_agent():
    agent = TaipeiAgent()

    messages = [
        # {"role": "user", "message": "你好，請問你能做什麼？"},
        # {"role": "user", "message": "幫我搜尋台北現在的交通情況"},
        {"role": "user", "message": "what is 1 + 1?"},
    ]

    history = None
    for msg in messages:
        if msg["role"] != "user":
            continue
        result = agent.chat(msg["message"], message_history=history)
        usage = result.usage()
        print(f"[usage] total tokens: {usage.total_tokens}")
        print(f"[user] {msg['message']}")
        print_tool_activity(result)
        print(f"[history] {len(history) if history else 0} messages in history")
        print(f"[agent] {result.output}\n")
        history = result.new_messages()

if __name__ == "__main__":
    test_taipei_agent()