from taipei_agent.taipei_agent import TaipeiAgent


async def test_taipei_agent():
    agent = TaipeiAgent()
    msg = {
        "role": "user",
        "content": "請問台北市的天氣如何？"
    }
    agent_response = await agent.chat([msg])
    print(agent_response)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_taipei_agent())