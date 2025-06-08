import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from bot.utils.decorators import admin_required
from bot.presentation.keyboard import create_stats_main_menu_keyboard
from bot.context import CustomContext
from bot.platforms import PLATFORMS

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: CustomContext) -> None:
    """Sends a welcome message and logs the user interaction."""
    user = update.effective_user
    message = update.message
    if not message or not user:
        logger.warning("Start command received without message or user.")
        return

    db_manager = context.db_manager

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

    # Get all supported platforms dynamically (exclude Generic platform)
    supported_platforms = [platform.name for platform in PLATFORMS if platform.name != "Video Platform"]

    # Create platform list for display
    platform_list = ""
    for i, platform in enumerate(supported_platforms, 1):
        platform_list += f"• {platform}\n"

    welcome_text = (
        f"🎉 <b>Welcome to FoxyFetch!</b> 🦊\n\n"
        f"Hi {user.mention_html()}! I'm your personal video downloader bot.\n\n"
        f"📺 <b>Supported Platforms ({len(supported_platforms)}):</b>\n"
        f"{platform_list}\n"
        f"🚀 <b>How to use:</b>\n"
        f"1️⃣ Send me a video link from any supported platform\n"
        f"2️⃣ Choose your preferred quality (Best, 720p, 480p, Audio Only, or GIF)\n"
        f"3️⃣ Wait for me to process and upload your file!\n\n"
        f"💡 <b>Pro Tips:</b>\n"
        f"• You can reply to messages containing video links\n"
        f"• I support audio extraction and GIF conversion\n"
        f"• Files are automatically cleaned up after upload\n\n"
        f"Ready to start downloading? Just paste a video link! ⬇️"
    )

    await message.reply_html(welcome_text)

async def help_command(update: Update, context: CustomContext) -> None:
    """Provides detailed help information."""
    user = update.effective_user
    message = update.message
    if not message or not user:
        logger.warning("Help command received without message or user.")
        return

    db_manager = context.db_manager

    try:
        await db_manager.log_interaction(
            user_id=user.id,
            chat_id=message.chat_id,
            message_id=message.message_id,
            interaction_type='command',
            content='/help'
        )
    except Exception as e:
        logger.error(f"Database error logging /help command for user {user.id}: {e}", exc_info=True)

    help_text = (
        f"🆘 <b>FoxyFetch Help Guide</b>\n\n"
        f"<b>📋 Available Commands:</b>\n"
        f"• /start - Welcome message and platform list\n"
        f"• /help - This help message\n\n"
        f"<b>🎯 How to Download Videos:</b>\n"
        f"1️⃣ <b>Direct Link:</b> Send any supported video URL\n"
        f"2️⃣ <b>Reply Method:</b> Reply to a message containing a video link\n"
        f"3️⃣ <b>Quality Selection:</b> Choose from the options I provide\n\n"
        f"<b>📥 Download Options:</b>\n"
        f"🏆 <b>Best Quality:</b> Highest available video + audio\n"
        f"🎬 <b>Resolution Options:</b> 720p, 480p, 360p, etc.\n"
        f"🎵 <b>Audio Only:</b> Extract audio as M4A file\n"
        f"✨ <b>GIF Conversion:</b> Convert full video to animated GIF\n\n"
        f"<b>⚡ Features:</b>\n"
        f"• Fast processing with progress updates\n"
        f"• Automatic file cleanup\n"
        f"• Support for private/unlisted videos (if accessible)\n"
        f"• Multi-platform support\n\n"
        f"<b>❓ Need Support?</b>\n"
        f"Just send me a video link and I'll handle the rest! 🚀"
    )

    await message.reply_html(help_text)

@admin_required
async def stats_command(update: Update, context: CustomContext) -> None:
    """Displays the main statistics menu (admin only)."""
    message = update.message
    user = update.effective_user
    if not message or not user:
        logger.warning("Stats command received without message or user.")
        return

    db_manager = context.db_manager

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

    text = "📊 *Bot Statistics*\nSelect a category:"
    keyboard = create_stats_main_menu_keyboard()
    await message.reply_markdown(text, reply_markup=keyboard)

start_handler = CommandHandler(["start"], start_command)
help_handler = CommandHandler(["help"], help_command)
stats_handler = CommandHandler("stats", stats_command)
command_handlers = [start_handler, help_handler, stats_handler]
