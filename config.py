import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1800"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "bdpost.db")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Optional admin Telegram user/chat ID for receiving feedback directly in Telegram
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if ADMIN_CHAT_ID:
    try:
        ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
    except ValueError:
        pass

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")



