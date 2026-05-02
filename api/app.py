from contextlib import asynccontextmanager

from fastapi import FastAPI

from observability import setup_logfire
from taipei_agent.taipei_agent import TaipeiAgent

from .chat import router as chat_router

setup_logfire()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup code here (if any)
    agent = TaipeiAgent()  # warm up the agent at startup
    app.state.agent = agent
    yield
    # shutdown code here (if any)

app = FastAPI()
app.include_router(chat_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True)