from taipei_agent.taipei_agent import TaipeiAgent


async def test_taipei_agent():
    agent = TaipeiAgent()
    # Single turn
    result = await agent.chat("台北今天天氣如何？")
    print(result.output)

    # Multi-turn (pass history to keep context)
    result2 = await agent.chat("明天呢？", message_history=result.new_messages())
    print(result2.output)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_taipei_agent())