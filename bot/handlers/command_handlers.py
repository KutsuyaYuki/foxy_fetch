import logging
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

# Import admin decorator and DB functions
from bot.utils.decorators import admin_required
import bot.database as db
from bot.presentation.keyboard import create_stats_main_menu_keyboard # Import stats keyboard

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and logs the user interaction."""
    user = update.effective_user
    message = update.message
    if not message or not user: return

    # Log user and interaction
    try:
        await db.upsert_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        await db.log_interaction(
            user_id=user.id,
            chat_id=message.chat_id,
            message_id=message.message_id,
            interaction_type='command',
            content=message.text or "/start" # Use text or default
        )
        logger.info(f"User {user.id} ({user.username}) started bot. Interaction logged.")
    except Exception as e:
        logger.error(f"Database error during start command for user {user.id}: {e}", exc_info=True)

    await message.reply_html(
        rf"Hi {user.mention_html()}! Send me a YouTube link (or reply) and I'll help you download it.",
    )

# --- Stats Command (Admin Only) ---
@admin_required
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the main statistics menu (admin only)."""
    message = update.message
    user = update.effective_user
    if not message or not user: return # Should be caught by decorator, but good practice

    # Log admin interaction
    try:
        await db.log_interaction(
            user_id=user.id,
            chat_id=message.chat_id,
            message_id=message.message_id,
            interaction_type='command',
            content='/stats'
        )
    except Exception as e:
        logger.error(f"Database error logging /stats command for admin {user.id}: {e}", exc_info=True)

    text = "📊 *Bot Statistics*\nSelect a category:"
    keyboard = create_stats_main_menu_keyboard()
    await message.reply_markdown(text, reply_markup=keyboard)

# --- Handler Registration ---
start_handler = CommandHandler(["start", "help"], start_command)
# Add the new stats handler
stats_handler = CommandHandler("stats", stats_command)

# List of command handlers to register in main.py
# Add stats_handler to the list
command_handlers = [start_handler, stats_handler]
