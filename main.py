import logging
from telegram.ext import Application, Defaults
from telegram.constants import ParseMode

# Import necessary components from the bot package
from bot.config import BOT_TOKEN
from bot.handlers import handlers

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
# Set PTB logging to WARNING to reduce verbosity, INFO for more details
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

def main() -> None:
    """Starts the bot."""
    if not BOT_TOKEN:
        logger.critical("Bot token not provided. Exiting.")
        return

    # Set default parse mode for messages
    defaults = Defaults(parse_mode=ParseMode.HTML) # Or MARKDOWN if preferred

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

    # Register handlers
    for handler in handlers:
        application.add_handler(handler)

    # Start the Bot
    logger.info("Starting bot polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
