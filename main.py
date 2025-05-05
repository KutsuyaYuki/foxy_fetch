import logging
import httpx # Import httpx for Timeout object
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode

# Import necessary components from the bot package
from bot.config import (
    BOT_TOKEN,
    USE_LOCAL_API_SERVER,
    LOCAL_BOT_API_SERVER_URL
)
from bot.handlers import handlers

# Enable logging (keep existing setup)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Define Timeouts ---
# Default timeouts (in seconds)
DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 20.0
DEFAULT_WRITE_TIMEOUT = 30.0

# Increased timeouts for potentially slow local server / large uploads
LOCAL_SERVER_CONNECT_TIMEOUT = 15.0
LOCAL_SERVER_READ_TIMEOUT = 300.0 # 5 minutes for reading response / upload
LOCAL_SERVER_WRITE_TIMEOUT = 300.0 # 5 minutes for sending data / upload

def main() -> None:
    """Starts the bot."""
    if not BOT_TOKEN:
        logger.critical("Bot token not provided. Exiting.")
        return

    defaults = Defaults(parse_mode=ParseMode.HTML)

    # Determine timeouts based on server type
    if USE_LOCAL_API_SERVER:
        connect_timeout = LOCAL_SERVER_CONNECT_TIMEOUT
        read_timeout = LOCAL_SERVER_READ_TIMEOUT
        write_timeout = LOCAL_SERVER_WRITE_TIMEOUT
        logger.info(f"Using increased timeouts for local server: Connect={connect_timeout}s, Read={read_timeout}s, Write={write_timeout}s")
    else:
        connect_timeout = DEFAULT_CONNECT_TIMEOUT
        read_timeout = DEFAULT_READ_TIMEOUT
        write_timeout = DEFAULT_WRITE_TIMEOUT
        logger.info(f"Using default timeouts: Connect={connect_timeout}s, Read={read_timeout}s, Write={write_timeout}s")


    # Create the Application Builder with timeouts
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .defaults(defaults)
        .connect_timeout(connect_timeout)
        .read_timeout(read_timeout)
        .write_timeout(write_timeout)
        # Note: For very fine-grained control, PTB also supports passing an httpx.Timeout object
        # .http_version("1.1") # Keep default unless needed
        # .pool_timeout(60.0) # Timeout for getting connection from pool
    )

    # Conditionally configure for Local Bot API Server
    if USE_LOCAL_API_SERVER and LOCAL_BOT_API_SERVER_URL:
        logger.info(f"Configuring Application to use Local Bot API Server: {LOCAL_BOT_API_SERVER_URL}")
        builder = builder.base_url(f"{LOCAL_BOT_API_SERVER_URL}/bot{{token}}")
        builder = builder.base_file_url(f"{LOCAL_BOT_API_SERVER_URL}/file/bot{{token}}")
    else:
        logger.info("Configuring Application to use Default Telegram Bot API Servers.")

    # Build the Application
    application = builder.build()

    # Register handlers
    for handler in handlers:
        application.add_handler(handler)

    # Start the Bot
    logger.info("Starting bot polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
