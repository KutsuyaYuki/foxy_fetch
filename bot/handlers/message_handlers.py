import logging
import re
import asyncio
from typing import Optional, List, Dict, Tuple, Any

from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters
import aiosqlite # Import needed for type hint

from bot.helpers import is_valid_youtube_url
from bot.services.youtube_service import YouTubeService
from bot.exceptions import ServiceError
from bot.presentation.keyboard import create_quality_options_keyboard
import bot.database as db

logger = logging.getLogger(__name__)

YOUTUBE_URL_IN_TEXT_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/[\w\-/?=&#%]+")

def find_youtube_url_in_message(message: Optional[Message]) -> Optional[str]:
    if not message: return None
    text_to_check = message.text or message.caption or ""
    match = YOUTUBE_URL_IN_TEXT_REGEX.search(text_to_check)
    if match: url = match.group(0); return url if is_valid_youtube_url(url) else None
    return None

def process_formats(formats: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # ... (function remains the same) ...
    available_options: Dict[int, Dict[str, Any]] = {}; valid_vcodec_prefixes = ('avc', 'h264', 'vp9', 'av01')
    min_height = 240; best_overall_format_data = None; best_height = 0
    for f in formats:
        if f.get('vcodec') == 'none' or not f.get('height'): continue
        height = f.get('height', 0); vcodec: str = f.get('vcodec', 'none').lower()
        if height < min_height or not any(vcodec.startswith(prefix) for prefix in valid_vcodec_prefixes): continue
        pref_val = f.get('preference'); current_pref = pref_val if isinstance(pref_val, (int, float)) else -1
        stored_pref = -1
        if height in available_options: stored_pref_val = available_options[height].get('preference'); stored_pref = stored_pref_val if isinstance(stored_pref_val, (int, float)) else -1
        if height not in available_options or current_pref > stored_pref: available_options[height] = {'height': height, 'selector': f'h{height}', 'preference': current_pref}
        current_best_pref = -1
        if best_overall_format_data: best_pref_val = best_overall_format_data.get('preference'); current_best_pref = best_pref_val if isinstance(best_pref_val, (int, float)) else -1
        if height >= best_height and (height > best_height or current_pref > current_best_pref): best_height = height; best_overall_format_data = available_options[height].copy()
    if best_overall_format_data: best_option_for_keyboard = best_overall_format_data.copy(); best_option_for_keyboard['selector'] = 'best'
    else: best_option_for_keyboard = {'height': 0, 'selector': 'best', 'preference': -1}; logger.warning("Could not determine best format.")
    quality_options_for_keyboard = list(available_options.values())
    sorted_options = sorted(quality_options_for_keyboard, key=lambda x: x['height'], reverse=True)
    return sorted_options, best_option_for_keyboard


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages, detects URLs, fetches info, logs, and sends options."""
    if not update.message or not context.bot: return
    trigger_message: Message = update.message
    user = update.effective_user
    if not user:
        logger.warning("Cannot handle message: effective_user is None.")
        return

    # --- Get DB connection ---
    db_connection: Optional[aiosqlite.Connection] = context.bot_data.get('db_connection')
    if not db_connection:
        logger.error("Database connection not found in context for handle_message.")
        await trigger_message.reply_text("Sorry, an internal error occurred (DB connection). Please try again later.")
        return
    # -----------------------

    url_to_process: Optional[str] = None
    interaction_type = 'url_message'

    if trigger_message.reply_to_message:
        url_to_process = find_youtube_url_in_message(trigger_message.reply_to_message)
        if url_to_process:
            interaction_type = 'reply_message'
    if not url_to_process:
        url_to_process = find_youtube_url_in_message(trigger_message)

    if not url_to_process:
        logger.debug(f"No valid YouTube URL found in message {trigger_message.message_id} from user {user.id}")
        return

    logger.info(f"Found URL: {url_to_process} in {interaction_type} from user {user.id}. Processing request...")

    interaction_id: Optional[int] = None
    try:
        # --- Pass connection to DB functions ---
        await db.upsert_user(
            db_connection, # Pass connection
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        interaction_id = await db.log_interaction(
            db_connection, # Pass connection
            user_id=user.id,
            chat_id=trigger_message.chat_id,
            message_id=trigger_message.message_id,
            interaction_type=interaction_type,
            content=trigger_message.text or trigger_message.caption or url_to_process
        )
        logger.debug(f"Logged interaction {interaction_id} for URL request from user {user.id}")
    except Exception as e:
        logger.error(f"Database error logging URL interaction for user {user.id}: {e}", exc_info=True)
        # Proceed but maybe log failure?

    status_message = None
    chat_id = trigger_message.chat_id
    youtube_service = YouTubeService()

    try:
        # Send initial status message
        status_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Processing YouTube link...")
        await asyncio.sleep(0.1)

        video_details = await youtube_service.get_video_details(url_to_process)
        title = video_details['title']
        duration = video_details['duration']
        formats = video_details['formats']

        if duration and duration > 3600 * 2:
             logger.warning(f"Video {url_to_process} too long ({duration}s) for user {user.id}")
             await status_message.edit_text("❌ Video is too long (> 2 hours).")
             # Here, you might want to update the download record to failed if one was created,
             # but no download record is created at this stage yet.
             return
        if not formats:
             logger.warning(f"Could not find formats for {url_to_process} for user {user.id}")
             await status_message.edit_text("❌ Could not find download formats for this video.")
             return

        quality_options, best_quality_option = process_formats(formats)
        if best_quality_option.get('height', 0) == 0 and not quality_options:
             logger.warning(f"No suitable video formats found for {url_to_process} after processing for user {user.id}")
             await status_message.edit_text("❌ No suitable video formats found (check resolution/availability).")
             return

        caption = f"🎬 **{title}**\n\nSelect download quality:"
        keyboard = create_quality_options_keyboard(url_to_process, quality_options, best_quality_option)

        await status_message.edit_text(
             text=caption, parse_mode=ParseMode.MARKDOWN,
             reply_markup=keyboard, disable_web_page_preview=True
        )
        logger.info(f"Presented quality options for {url_to_process} to user {user.id} in message {status_message.message_id}")

    except (ServiceError, Exception) as e:
        error_text = f"❌ Error processing link: {e}"
        logger.error(f"Error handling message for URL {url_to_process} from user {user.id}: {e}", exc_info=(not isinstance(e, ServiceError)))
        if status_message:
            try: await status_message.edit_text(error_text[:4000])
            except Exception: logger.error("Failed to edit status message with error.")
        else:
            await trigger_message.reply_text(error_text[:4000], quote=True)

# Define filters
url_message_filter = filters.TEXT & ~filters.COMMAND & ~filters.REPLY
reply_filter = filters.REPLY & ~filters.COMMAND

# Create handlers
url_message_handler = MessageHandler(url_message_filter, handle_message)
reply_handler = MessageHandler(reply_filter, handle_message)

# List of handlers
message_handlers = [url_message_handler, reply_handler]
