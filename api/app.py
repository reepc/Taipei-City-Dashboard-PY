import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from config import PROXY_ENABLED
from observability import setup_logfire
from taipei_agent.taipei_agent import TaipeiAgent

from .chat import router as chat_router
from .proxy_register import keepalive_loop

setup_logfire()

@asynccontextmanager
async def lifespan(app: FastAPI):
    agent = TaipeiAgent()  # warm up the agent at startup
    app.state.agent = agent

    proxy_task: asyncio.Task | None = None
    if PROXY_ENABLED:
        proxy_task = asyncio.create_task(keepalive_loop())

    try:
        yield
    finally:
        if proxy_task is not None:
            proxy_task.cancel()
            try:
                await proxy_task
            except asyncio.CancelledError:
                pass

app = FastAPI(lifespan=lifespan)

_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/dev/ping", response_class=PlainTextResponse)
async def proxy_ping() -> str:
    """BE dynamic-proxy health check; must return literal 'pong'."""
    return "pong"


app.include_router(chat_router, prefix="/api/dev")

if __name__ == "__main__":
    import uvicorn

    from config import HOST, PORT

    uvicorn.run("api.app:app", host=HOST, port=PORT, reload=True)