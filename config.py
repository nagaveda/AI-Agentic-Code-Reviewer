import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2048
