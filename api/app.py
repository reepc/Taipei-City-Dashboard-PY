from fastapi import FastAPI

from observability import setup_logfire

from api.chat import router as chat_router

setup_logfire()

app = FastAPI()
app.include_router(chat_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True)