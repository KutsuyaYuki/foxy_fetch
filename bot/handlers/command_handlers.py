import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
    user = update.effective_user
    if not update.message or not user: return
    logger.info(f"User {user.id} started bot")
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Send me a YouTube link (or reply) and I'll help you download it.",
    )

start_handler = CommandHandler(["start", "help"], start_command)

# List of command handlers to register in main.py
command_handlers = [start_handler]
