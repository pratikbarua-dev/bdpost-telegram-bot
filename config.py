import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1800"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "bdpost.db")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
