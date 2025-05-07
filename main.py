import logging
import logging.handlers
import os
import asyncio
from typing import Optional, Dict, Any

from telegram import Update
from telegram.ext import Application, Defaults, ContextTypes
from telegram.constants import ParseMode

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
from bot.database import DatabaseManager # Changed import

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

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 20.0
DEFAULT_WRITE_TIMEOUT = 30.0
LOCAL_SERVER_CONNECT_TIMEOUT = 15.0
LOCAL_SERVER_READ_TIMEOUT = 300.0
LOCAL_SERVER_WRITE_TIMEOUT = 300.0

class CustomContext(ContextTypes.DEFAULT_TYPE):
    bot_data: Dict[str, Any]
    _db_manager: Optional[DatabaseManager] = None # Store DatabaseManager instance

    def __init__(self, application: Application, chat_id: Optional[int] = None, user_id: Optional[int] = None):
        super().__init__(application=application, chat_id=chat_id, user_id=user_id)
        # bot_data is managed by the Application, db_manager is specific to context instances if needed,
        # but for a global manager, it's better in application.bot_data

    @property
    def db_manager(self) -> DatabaseManager:
        """Provides access to the DatabaseManager instance stored in application.bot_data."""
        manager = self.application.bot_data.get('db_manager')
        if not isinstance(manager, DatabaseManager):
            # This should not happen if post_init runs correctly
            logger.critical("DatabaseManager not found in application.bot_data or is of incorrect type.")
            raise RuntimeError("DatabaseManager not initialized correctly.")
        return manager


async def post_application_init(application: Application) -> None:
    """Initialize and store the DatabaseManager."""
    logger.info("Initializing DatabaseManager...")
    db_manager = DatabaseManager(DATABASE_FILE)
    try:
        await db_manager.connect()
        application.bot_data["db_manager"] = db_manager
        logger.info("DatabaseManager initialized and connection established.")
    except Exception as e:
        logger.critical(f"Failed to initialize DatabaseManager or connect to database: {e}", exc_info=True)
        # Depending on policy, you might want to raise the_exception to stop startup
        # For now, we log critically and the bot might run without DB.
        # Consider `application.stop()` or raising if DB is essential.


async def post_application_shutdown(application: Application) -> None:
    """Close the database connection via DatabaseManager."""
    logger.info("Shutting down DatabaseManager...")
    db_manager = application.bot_data.get("db_manager")
    if isinstance(db_manager, DatabaseManager):
        try:
            await db_manager.close()
            logger.info("DatabaseManager connection closed.")
        except Exception as e:
            logger.error(f"Error closing DatabaseManager connection: {e}", exc_info=True)
    else:
        logger.warning("No DatabaseManager found in bot_data to close or incorrect type.")


def main() -> None:
    logger.info("Starting bot application setup...")
    if not BOT_TOKEN:
        logger.critical("Bot token not provided. Exiting.")
        return

    try:
        DatabaseManager.sync_init_db(DATABASE_FILE)
    except Exception: # sync_init_db already logs critical and raises
         logger.critical("Stopping bot due to database schema initialization failure.")
         return

    context_types = ContextTypes(context=CustomContext)
    defaults = Defaults(parse_mode=ParseMode.HTML)

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

    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .defaults(defaults)
        .context_types(context_types)
        .connect_timeout(connect_timeout)
        .read_timeout(read_timeout)
        .write_timeout(write_timeout)
        .post_init(post_application_init)
        .post_shutdown(post_application_shutdown)
    )

    if USE_LOCAL_API_SERVER and LOCAL_BOT_API_SERVER_URL:
        logger.info(f"Using Local Bot API Server: {LOCAL_BOT_API_SERVER_URL}")
        builder = builder.base_url(f"{LOCAL_BOT_API_SERVER_URL}/bot{{token}}")
        builder = builder.base_file_url(f"{LOCAL_BOT_API_SERVER_URL}/file/bot{{token}}")
    else:
        logger.info("Using Default Telegram Bot API Servers.")

    application = builder.build()

    logger.info(f"Registering {len(all_handlers)} handlers...")
    for handler in all_handlers:
        application.add_handler(handler)

    logger.info("Starting bot polling...")
    try:
        application.run_polling()
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
    finally:
        logger.info("Bot polling stopped.")


if __name__ == "__main__":
    main()
