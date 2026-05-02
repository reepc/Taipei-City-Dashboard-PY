import os

import uvicorn

from config import HOST, PORT


if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host=HOST,
        port=PORT,
        reload=os.getenv("RELOAD", "true").lower() == "true",
    )
