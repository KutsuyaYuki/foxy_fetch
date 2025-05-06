import os
import logging
from dotenv import load_dotenv
from typing import Set

load_dotenv() # Load environment variables from .env file
logger = logging.getLogger(__name__) # Use logger for warnings

# --- Core Bot Token ---
BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
if BOT_TOKEN is None:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables or .env file.")

# --- Admin Users ---
# Load comma-separated admin IDs from .env
raw_admin_ids: str | None = os.getenv("ADMIN_USER_IDS")
ADMIN_IDS: Set[int] = set() # Use a set for efficient lookup

if raw_admin_ids:
    try:
        ADMIN_IDS = {int(admin_id.strip()) for admin_id in raw_admin_ids.split(',') if admin_id.strip()}
        if not ADMIN_IDS:
            logger.warning("ADMIN_USER_IDS found in .env but contained no valid integer IDs.")
        else:
            logger.info(f"Loaded Admin User IDs: {ADMIN_IDS}")
    except ValueError:
        logger.error("ADMIN_USER_IDS in .env contains non-integer values. No admins loaded.", exc_info=True)
else:
    logger.warning("ADMIN_USER_IDS not found in environment variables or .env file. No admins will have access to /stats.")

# Remove the hardcoded ID:
# ADMIN_USER_ID: int = 152662569 # <-- REMOVED

# --- Database ---
DATABASE_FILE: str = "bot_data.db"

# --- Logging ---
LOG_DIR: str = "logs"
LOG_FILE: str = os.path.join(LOG_DIR, "bot.log")
LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT: int = 5

# --- Download Directory ---
DOWNLOAD_DIR: str = "/tmp/foxyfetch" # Or choose a different temporary path
os.makedirs(DOWNLOAD_DIR, exist_ok=True) # Ensure download directory exists

# --- Local Bot API Server Configuration (Optional) ---
LOCAL_BOT_API_SERVER_URL: str | None = os.getenv("LOCAL_BOT_API_SERVER_URL")
USE_LOCAL_API_SERVER: bool = bool(LOCAL_BOT_API_SERVER_URL) # True if URL is set

TELEGRAM_API_ID: str | None = None
TELEGRAM_API_HASH: str | None = None

# --- Set Upload Limit based on Server Type ---
DEFAULT_MAX_UPLOAD_MB = 50
LOCAL_SERVER_MAX_UPLOAD_MB = 2000

if USE_LOCAL_API_SERVER:
    TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
    MAX_UPLOAD_SIZE_BYTES = LOCAL_SERVER_MAX_UPLOAD_MB * 1024 * 1024
    print(f"Using Local Bot API Server: {LOCAL_BOT_API_SERVER_URL}")
    print(f"Max Upload Size: {LOCAL_SERVER_MAX_UPLOAD_MB} MB")
else:
    MAX_UPLOAD_SIZE_BYTES = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    print(f"Using Default Telegram Bot API Server")
    print(f"Max Upload Size: {DEFAULT_MAX_UPLOAD_MB} MB")

# --- Ensure Log Directory Exists ---
os.makedirs(LOG_DIR, exist_ok=True)
