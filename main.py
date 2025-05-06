import logging
import httpx
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode

# Import necessary components from the bot package
from bot.config import (
    BOT_TOKEN,
    USE_LOCAL_API_SERVER,
    LOCAL_BOT_API_SERVER_URL
)
# --- Import the combined list from the handlers package ---
from bot.handlers import all_handlers
# --------------------------------------------------------

# Enable logging (keep existing setup)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Define Timeouts ---
DEFAULT_CONNECT_TIMEOUT = 10.0; DEFAULT_READ_TIMEOUT = 20.0; DEFAULT_WRITE_TIMEOUT = 30.0
LOCAL_SERVER_CONNECT_TIMEOUT = 15.0; LOCAL_SERVER_READ_TIMEOUT = 300.0; LOCAL_SERVER_WRITE_TIMEOUT = 300.0

def main() -> None:
    """Starts the bot."""
    if not BOT_TOKEN:
        logger.critical("Bot token not provided. Exiting.")
        return

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

if __name__ == "__main__":
    main()
