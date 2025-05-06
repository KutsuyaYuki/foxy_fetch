import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

# --- Core Bot Token ---
BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
if BOT_TOKEN is None:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables or .env file.")

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
