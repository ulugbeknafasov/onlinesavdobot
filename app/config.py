import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./onlinexarid.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
FERNET_KEY = os.getenv("FERNET_KEY", "")
STORE_NAME = os.getenv("STORE_NAME", "OnlineXarid")

BTS_BOT_SOURCE = os.getenv("BTS_BOT_SOURCE", "@btsrobot")
BTS_MONITOR_SESSION = os.getenv("BTS_MONITOR_SESSION", "storage/bts_monitor")

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
