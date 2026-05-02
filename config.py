import os
from load_dotenv import load_dotenv


load_dotenv()


TWCC_LLAMA_FFM_API_KEY = os.getenv("TWCC_API_KEY")
TWCC_LLAMA_FFM_API_URL = os.getenv("TWCC_API_URL")
TWCC_LLAMA_FFM_MODEL = os.getenv("TWCC_MODEL", "llama3.3-ffm-70b-16k-chat")