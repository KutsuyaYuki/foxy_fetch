import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler
from telegram.error import TelegramError, BadRequest
from telegram.constants import ParseMode

from bot.config import ADMIN_IDS
from bot.presentation.keyboard import (
    create_stats_main_menu_keyboard,
    create_stats_submenu_keyboard
)
from bot.context import CustomContext
from .utils import parse_stats_callback

logger = logging.getLogger(__name__)

async def handle_stats_callback(update: Update, context: CustomContext) -> None:
    """Handle button presses for the statistics interface (admin only)."""
    query = update.callback_query
    user = update.effective_user

    if not query or not query.message or not query.data or not user:
        logger.warning("Stats callback received invalid data or missing components.")
        if query:
            await query.answer("Invalid request.", show_alert=True)
        return

    # Check admin permissions
    if user.id not in ADMIN_IDS:
        logger.warning(f"Non-admin user {user.id} tried to use stats callback: {query.data}")
        await query.answer("Access Denied.", show_alert=True)
        return

    db_manager = context.db_manager
    await query.answer()

    try:
        # Log interaction
        await db_manager.log_interaction(
            user_id=user.id, chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            interaction_type='callback_query', content=query.data
        )
    except ConnectionError as ce:
        logger.error(f"DB connection error logging stats callback for admin {user.id}: {ce}")
        await query.edit_message_text("❌ Internal Error (DB Connection). Please try again later.")
        return
    except Exception as e:
        logger.error(f"Database error logging stats callback for admin {user.id}: {e}", exc_info=True)

    # Parse callback data
    parsed_data = parse_stats_callback(query.data)
    if not parsed_data:
        logger.error(f"Invalid stats callback data format: {query.data} from admin {user.id}")
        try:
            await query.edit_message_text("❌ Invalid stats request format.")
        except (TelegramError, BadRequest):
            pass
        return

    menu_type, action = parsed_data

    try:
        text, keyboard = await _process_stats_request(db_manager, menu_type, action)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    except ConnectionError as ce:
        logger.error(f"DB connection error handling stats callback action '{action}' for admin {user.id}: {ce}")
        await query.edit_message_text("❌ A database connection error occurred while fetching statistics.")
    except Exception as e:
        logger.exception(f"Error handling stats callback action '{action}' for admin {user.id}")
        try:
            await query.edit_message_text("❌ An error occurred while fetching statistics.")
        except (TelegramError, BadRequest):
            pass

async def _process_stats_request(db_manager, menu_type: str, action: str) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Process the stats request and return text and keyboard."""
    text = "📊 *Bot Statistics*\n\n"
    keyboard: Optional[InlineKeyboardMarkup] = None

    # Calculate time ranges
    now_utc = datetime.now(timezone.utc)
    one_day_ago_iso = (now_utc - timedelta(days=1)).isoformat()
    seven_days_ago_iso = (now_utc - timedelta(days=7)).isoformat()

    if menu_type == "stats_menu":
        text, keyboard = await _handle_stats_menu(action)
    elif menu_type == "stats_show":
        text, keyboard = await _handle_stats_show(db_manager, action, one_day_ago_iso, seven_days_ago_iso)
    else:
        logger.error(f"Unknown stats menu type: {menu_type}")
        text = "Error: Unknown statistics menu."
        keyboard = create_stats_main_menu_keyboard()

    return text, keyboard

async def _handle_stats_menu(action: str) -> tuple[str, InlineKeyboardMarkup]:
    """Handle stats menu navigation."""
    text = "📊 *Bot Statistics*\n\n"

    if action == "main":
        text += "Select a category:"
        keyboard = create_stats_main_menu_keyboard()
    elif action == "users":
        text += "👤 *User Statistics*\nSelect an option:"
        keyboard = create_stats_submenu_keyboard("users")
    elif action == "interactions":
        text += "💬 *Interaction Statistics*\nSelect an option:"
        keyboard = create_stats_submenu_keyboard("interactions")
    elif action == "downloads":
        text += "📥 *Download Statistics*\nSelect an option:"
        keyboard = create_stats_submenu_keyboard("downloads")
    else:
        logger.warning(f"Unknown stats menu action: {action}")
        text += "Unknown menu."
        keyboard = create_stats_main_menu_keyboard()

    return text, keyboard

async def _handle_stats_show(db_manager, action: str, one_day_ago: str, seven_days_ago: str) -> tuple[str, InlineKeyboardMarkup]:
    """Handle stats data display."""
    text = "📊 *Bot Statistics*\n\n"
    back_button = InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="stats_menu:main")]])

    if action == "summary":
        text += await _get_summary_stats(db_manager, one_day_ago)
        keyboard = back_button
    elif action.startswith("users_"):
        text += await _get_user_stats(db_manager, action, one_day_ago, seven_days_ago)
        keyboard = create_stats_submenu_keyboard("users")
    elif action.startswith("interactions_"):
        text += await _get_interaction_stats(db_manager, action, one_day_ago)
        keyboard = create_stats_submenu_keyboard("interactions")
    elif action.startswith("downloads_"):
        text += await _get_download_stats(db_manager, action)
        keyboard = create_stats_submenu_keyboard("downloads")
    else:
        logger.warning(f"Unknown stats show action: {action}")
        text += "Unknown statistics view."
        keyboard = create_stats_main_menu_keyboard()

    return text, keyboard

async def _get_summary_stats(db_manager, one_day_ago: str) -> str:
    """Get overall summary statistics."""
    total_users = await db_manager.get_total_user_count()
    active_24h = await db_manager.get_users_count(one_day_ago)
    status_counts = await db_manager.get_download_status_counts()
    completed_downloads = status_counts.get('completed', 0)
    failed_downloads = status_counts.get('failed', 0)
    total_dl_attempts = sum(status_counts.values())
    success_rate = (completed_downloads / total_dl_attempts * 100) if total_dl_attempts > 0 else 0.0

    return (
        f"📊 *Overall Summary*\n"
        f"- Total Users: `{total_users}`\n"
        f"- Active Users (24h): `{active_24h}`\n"
        f"- Total Download Attempts: `{total_dl_attempts}`\n"
        f"- Completed Downloads: `{completed_downloads}` ✅\n"
        f"- Failed Downloads: `{failed_downloads}` ❌\n"
        f"- Success Rate: `{success_rate:.2f}%`\n"
    )

async def _get_user_stats(db_manager, action: str, one_day_ago: str, seven_days_ago: str) -> str:
    """Get user statistics."""
    if action == "users_total":
        count = await db_manager.get_total_user_count()
        return f"👤 Total Unique Users: `{count}`"
    elif action == "users_active_24h":
        count = await db_manager.get_users_count(one_day_ago)
        return f"👤 Active Users (last 24h): `{count}`"
    elif action == "users_active_7d":
        count = await db_manager.get_users_count(seven_days_ago)
        return f"👤 Active Users (last 7 days): `{count}`"
    return "Unknown user statistic."

async def _get_interaction_stats(db_manager, action: str, one_day_ago: str) -> str:
    """Get interaction statistics."""
    if action == "interactions_by_type":
        counts = await db_manager.get_interaction_count_by_type()
        text = "💬 *Interactions by Type (All Time)*\n"
        if counts:
            for type_name, count_val in sorted(counts.items()):
                text += f"- {type_name.replace('_', ' ').title()}: `{count_val}`\n"
        else:
            text += "_No interactions recorded._\n"
        return text
    elif action == "interactions_24h":
        counts = await db_manager.get_interaction_count_by_type(since_iso_timestamp=one_day_ago)
        text = "💬 *Interactions by Type (Last 24h)*\n"
        if counts:
            for type_name, count_val in sorted(counts.items()):
                text += f"- {type_name.replace('_', ' ').title()}: `{count_val}`\n"
        else:
            text += "_No interactions in the last 24 hours._\n"
        return text
    return "Unknown interaction statistic."

async def _get_download_stats(db_manager, action: str) -> str:
    """Get download statistics."""
    if action == "downloads_by_status":
        counts = await db_manager.get_download_status_counts()
        text = "📥 *Downloads by Status (All Time)*\n"
        if counts:
            for status_name, count_val in sorted(counts.items()):
                text += f"- {status_name.title()}: `{count_val}`\n"
        else:
            text += "_No downloads recorded._\n"
        return text
    elif action == "downloads_by_quality":
        counts = await db_manager.get_downloads_by_quality_summary()
        text = "📥 *Completed Downloads by Quality*\n"
        if counts:
            for quality_name, count_val in sorted(counts.items()):
                display_name = quality_name.replace('h', '').upper() if quality_name.startswith('h') else quality_name.title()
                text += f"- {display_name}: `{count_val}`\n"
        else:
            text += "_No completed downloads recorded._\n"
        return text
    elif action == "downloads_top_urls":
        urls = await db_manager.get_top_requested_urls(limit=5)
        text = "📥 *Top 5 Requested URLs*\n"
        if urls:
            for i, (url_item, count_val) in enumerate(urls):
                display_url = url_item[:60] + '...' if len(url_item) > 60 else url_item
                text += f"{i+1}. `{display_url}` (Count: `{count_val}`)\n"
        else:
            text += "_No URLs requested yet._\n"
        return text
    return "Unknown download statistic."

stats_callback_handler = CallbackQueryHandler(handle_stats_callback, pattern=r"^stats_(menu|show):.*")
