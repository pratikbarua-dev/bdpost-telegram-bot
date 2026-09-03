import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "1800"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "bdpost.db")
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Admin Telegram user/chat ID for full bot management and notifications
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6856606568"))

# Optional Cloudflare Worker proxy to route international requests through Cloudflare's edge network
CF_PROXY_URL = os.getenv("CF_PROXY_URL")
CF_PROXY_SECRET = os.getenv("CF_PROXY_SECRET")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")



