import os
from pathlib import Path
from load_dotenv import load_dotenv


load_dotenv()


ROOT_DIT = os.path.dirname(os.path.abspath(__file__))
ALL_COMPONENTS_PATH = Path(ROOT_DIT) / "components_no_id.json"

TWCC_LLAMA_FFM_API_KEY = os.getenv("TWCC_API_KEY")
TWCC_LLAMA_FFM_API_URL = os.getenv("TWCC_API_URL")
TWCC_LLAMA_FFM_MODEL = os.getenv("TWCC_MODEL", "llama3.3-ffm-70b-16k-chat")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", f"http://localhost:{PORT}")
NAVIGATE_BASE_URL = os.getenv("NAVIGATE_BASE_URL", "https://openrouteservice.ydtw.net")

# Dynamic reverse proxy registration (see docs/dyn-proxy-downstream.md).
# BE_BASE_URL: main backend that exposes /api/v1/proxy/{register,detach}.
# PROXY_NAME: entry key on BE; BE will route /api/v1/<PROXY_NAME>/... to us.
# PROXY_ADVERTISE_ADDR: host:port BE uses to reach us (must be reachable from BE).
# PROXY_KEEPALIVE_SEC: re-register interval; covers BE restarts.
BE_BASE_URL = os.getenv("BE_BASE_URL", "http://localhost:8080")
PROXY_NAME = os.getenv("PROXY_NAME", "chat")
PROXY_ADVERTISE_ADDR = os.getenv("PROXY_ADVERTISE_ADDR", f"localhost:{PORT}")
PROXY_KEEPALIVE_SEC = int(os.getenv("PROXY_KEEPALIVE_SEC", "30"))
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "true").lower() == "true"