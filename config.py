import os
from pathlib import Path
from load_dotenv import load_dotenv


load_dotenv()


ROOT_DIT = os.path.dirname(os.path.abspath(__file__))
ALL_COMPONENTS_PATH = Path(ROOT_DIT) / "all_components.json"

TWCC_LLAMA_FFM_API_KEY = os.getenv("TWCC_API_KEY")
TWCC_LLAMA_FFM_API_URL = os.getenv("TWCC_API_URL")
TWCC_LLAMA_FFM_MODEL = os.getenv("TWCC_MODEL", "llama3.3-ffm-70b-16k-chat")

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")