import logging
import logging.handlers
import os
import asyncio # Needed for running init_db
import httpx
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode

# Import necessary components from the bot package
from bot.config import (
    BOT_TOKEN,
    USE_LOCAL_API_SERVER,
    LOCAL_BOT_API_SERVER_URL,
    LOG_DIR, # Import log config
    LOG_FILE,
    LOG_MAX_BYTES,
    LOG_BACKUP_COUNT
)
# --- Import the combined list from the handlers package ---
from bot.handlers import all_handlers
# --- Import database initializer ---
from bot.database import init_db

# --- Setup Logging ---
# Remove basicConfig, configure root logger with handlers

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Create formatter
log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Create console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO) # Or desired level for console

# Create rotating file handler
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding='utf-8' # Explicitly set encoding
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO) # Or desired level for file

# Get the root logger and add handlers
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO) # Set lowest level for root logger
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Set higher levels for noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING) # Covers bot, ext, etc.
# logging.getLogger("telegram.ext").setLevel(logging.WARNING) # Covered by above
# logging.getLogger("telegram.bot").setLevel(logging.WARNING) # Covered by above
logging.getLogger("aiosqlite").setLevel(logging.WARNING) # Keep aiosqlite quiet unless error
logging.getLogger("yt_dlp").setLevel(logging.WARNING)


# Get our specific application logger
logger = logging.getLogger(__name__) # Use __name__ for module-specific logger
# --- End Logging Setup ---


# --- Define Timeouts ---
DEFAULT_CONNECT_TIMEOUT = 10.0; DEFAULT_READ_TIMEOUT = 20.0; DEFAULT_WRITE_TIMEOUT = 30.0
LOCAL_SERVER_CONNECT_TIMEOUT = 15.0; LOCAL_SERVER_READ_TIMEOUT = 300.0; LOCAL_SERVER_WRITE_TIMEOUT = 300.0

async def setup_database():
    """Initialize the database."""
    await init_db()

def main() -> None:
    """Starts the bot."""
    logger.info("Starting bot application...")
    if not BOT_TOKEN:
        logger.critical("Bot token not provided. Exiting.")
        return

    # --- Initialize Database Asynchronously Before Building App ---
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(setup_database())
    except Exception as e:
         logger.critical(f"Database initialization failed: {e}", exc_info=True)
         return # Stop if DB fails
    # --- End Database Initialization ---

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
        .connect_timeout(connect_timeout)
        .read_timeout(read_timeout)
        .write_timeout(write_timeout)
    )

    # Conditionally configure for Local Server
    if USE_LOCAL_API_SERVER and LOCAL_BOT_API_SERVER_URL:
        logger.info(f"Using Local Bot API Server: {LOCAL_BOT_API_SERVER_URL}")
        builder = builder.base_url(f"{LOCAL_BOT_API_SERVER_URL}/bot{{token}}")
        builder = builder.base_file_url(f"{LOCAL_BOT_API_SERVER_URL}/file/bot{{token}}")
    else:
        logger.info("Using Default Telegram Bot API Servers.")

    application = builder.build()

    # --- Register handlers using the combined list ---
    logger.info(f"Registering {len(all_handlers)} handlers...")
    for handler in all_handlers:
        application.add_handler(handler)
    # -----------------------------------------------

    logger.info("Starting bot polling...")
    application.run_polling()
    logger.info("Bot polling stopped.")

if __name__ == "__main__":
    main()
