import logging
import logging.handlers
import os
import asyncio
import httpx
import aiosqlite
# --- Import typing hints ---
from typing import Optional, Dict, Any
# ---------------------------
from telegram import Update
from telegram.ext import Application, Defaults, ContextTypes
from telegram.constants import ParseMode

# Import necessary components from the bot package
from bot.config import (
    BOT_TOKEN,
    USE_LOCAL_API_SERVER,
    LOCAL_BOT_API_SERVER_URL,
    LOG_DIR,
    LOG_FILE,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT,
    DATABASE_FILE
)
from bot.handlers import all_handlers
from bot.database import sync_init_db

# --- Logging Setup (remains the same) ---
os.makedirs(LOG_DIR, exist_ok=True)
log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding='utf-8'
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
# --- End Logging Setup ---

# --- Define Timeouts ---
DEFAULT_CONNECT_TIMEOUT = 10.0; DEFAULT_READ_TIMEOUT = 20.0; DEFAULT_WRITE_TIMEOUT = 30.0
LOCAL_SERVER_CONNECT_TIMEOUT = 15.0; LOCAL_SERVER_READ_TIMEOUT = 300.0; LOCAL_SERVER_WRITE_TIMEOUT = 300.0

# --- Application Lifecycle Hooks ---
async def post_application_init(application: Application) -> None:
    """Create and store the persistent database connection."""
    logger.info("Creating persistent database connection...")
    try:
        db_conn = await aiosqlite.connect(DATABASE_FILE)
        db_conn.row_factory = aiosqlite.Row
        try:
            await db_conn.execute("PRAGMA journal_mode=WAL;")
        except Exception as e:
            logger.warning(f"Could not enable WAL mode for persistent connection: {e}")

        application.bot_data["db_connection"] = db_conn
        logger.info("Persistent database connection established and stored.")
    except Exception as e:
        logger.critical(f"Failed to create persistent database connection: {e}", exc_info=True)

async def post_application_shutdown(application: Application) -> None:
    """Close the persistent database connection."""
    logger.info("Closing persistent database connection...")
    db_conn = application.bot_data.get("db_connection")
    if db_conn:
        try:
            await db_conn.close()
            logger.info("Persistent database connection closed.")
        except Exception as e:
            logger.error(f"Error closing persistent database connection: {e}", exc_info=True)
    else:
        logger.warning("No persistent database connection found in bot_data to close.")
# --- End Lifecycle Hooks ---


def main() -> None:
    """Starts the bot."""
    logger.info("Starting bot application setup...")
    if not BOT_TOKEN:
        logger.critical("Bot token not provided. Exiting.")
        return

    # --- Initialize Database Schema Synchronously ---
    try:
        sync_init_db()
    except Exception as e:
         logger.critical("Stopping bot due to database schema initialization failure.")
         return
    # --- End Synchronous Database Initialization ---

    # --- Define Custom Context ---
    class CustomContext(ContextTypes.DEFAULT_TYPE):
        # Ensure bot_data type hint exists
        bot_data: Dict[str, Any]

        # __init__ with correct type hints
        def __init__(self, application: Application, chat_id: Optional[int] = None, user_id: Optional[int] = None):
              super().__init__(application=application, chat_id=chat_id, user_id=user_id)
              # Ensure db_connection key exists, even if None initially
              self.bot_data.setdefault("db_connection", None)

    context_types = ContextTypes(context=CustomContext)
    # --- End Custom Context ---


    defaults = Defaults(parse_mode=ParseMode.HTML)

    # Determine timeouts
    if USE_LOCAL_API_SERVER:
        connect_timeout, read_timeout, write_timeout = (
            LOCAL_SERVER_CONNECT_TIMEOUT, LOCAL_SERVER_READ_TIMEOUT, LOCAL_SERVER_WRITE_TIMEOUT
        )
        logger.info(f"Using increased timeouts: C={connect_timeout}s, R={read_timeout}s, W={write_timeout}s")
    else:
        connect_timeout, read_timeout, write_timeout = (
            DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT, DEFAULT_WRITE_TIMEOUT
        )
        logger.info(f"Using default timeouts: C={connect_timeout}s, R={read_timeout}s, W={write_timeout}s")

    # Create the Application Builder
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .defaults(defaults)
        .context_types(context_types) # Use custom context
        .connect_timeout(connect_timeout)
        .read_timeout(read_timeout)
        .write_timeout(write_timeout)
        .post_init(post_application_init)
        .post_shutdown(post_application_shutdown)
    )

    # Conditionally configure for Local Server
    if USE_LOCAL_API_SERVER and LOCAL_BOT_API_SERVER_URL:
        logger.info(f"Using Local Bot API Server: {LOCAL_BOT_API_SERVER_URL}")
        builder = builder.base_url(f"{LOCAL_BOT_API_SERVER_URL}/bot{{token}}")
        builder = builder.base_file_url(f"{LOCAL_BOT_API_SERVER_URL}/file/bot{{token}}")
    else:
        logger.info("Using Default Telegram Bot API Servers.")

    application = builder.build()

    # Register handlers
    logger.info(f"Registering {len(all_handlers)} handlers...")
    for handler in all_handlers:
        application.add_handler(handler)

    logger.info("Starting bot polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()
