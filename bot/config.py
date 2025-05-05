import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
DOWNLOAD_DIR: str = "/tmp/telegram_yt_downloads" # Or choose a different temporary path

if BOT_TOKEN is None:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables or .env file.")

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
