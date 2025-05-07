import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from bot.utils.decorators import admin_required
from bot.presentation.keyboard import create_stats_main_menu_keyboard
from bot.context import CustomContext # Import CustomContext for type hinting

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: CustomContext) -> None: # Use CustomContext
    """Sends a welcome message and logs the user interaction."""
    user = update.effective_user
    message = update.message
    if not message or not user:
        logger.warning("Start command received without message or user.")
        return

    db_manager = context.db_manager # Access DatabaseManager via context

    try:
        await db_manager.upsert_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        await db_manager.log_interaction(
            user_id=user.id,
            chat_id=message.chat_id,
            message_id=message.message_id,
            interaction_type='command',
            content=message.text or "/start"
        )
        logger.info(f"User {user.id} ({user.username}) started bot. Interaction logged.")
    except ConnectionError as ce:
        logger.error(f"Database connection error during start command for user {user.id}: {ce}")
        await message.reply_text("Sorry, a database connection error occurred. Please try again later.")
        return
    except Exception as e:
        logger.error(f"Database error during start command for user {user.id}: {e}", exc_info=True)
        await message.reply_text("Sorry, an internal error occurred while processing your request.")
        return

    await message.reply_html(
        rf"Hi {user.mention_html()}! Send me a YouTube link (or reply) and I'll help you download it.",
    )

@admin_required
async def stats_command(update: Update, context: CustomContext) -> None: # Use CustomContext
    """Displays the main statistics menu (admin only)."""
    message = update.message
    user = update.effective_user
    if not message or not user:
        logger.warning("Stats command received without message or user.")
        return

    db_manager = context.db_manager # Access DatabaseManager via context

    try:
        await db_manager.log_interaction(
            user_id=user.id,
            chat_id=message.chat_id,
            message_id=message.message_id,
            interaction_type='command',
            content='/stats'
        )
    except ConnectionError as ce:
        logger.error(f"Database connection error logging /stats command for admin {user.id}: {ce}")
        await message.reply_text("Sorry, a database connection error occurred.")
        return
    except Exception as e:
        logger.error(f"Database error logging /stats command for admin {user.id}: {e}", exc_info=True)
        # Do not send a message here, as the primary function might still work.

    text = "📊 *Bot Statistics*\nSelect a category:"
    keyboard = create_stats_main_menu_keyboard()
    await message.reply_markdown(text, reply_markup=keyboard)

start_handler = CommandHandler(["start", "help"], start_command)
stats_handler = CommandHandler("stats", stats_command)
command_handlers = [start_handler, stats_handler]
