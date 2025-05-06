import logging
import re
import asyncio # Keep asyncio if needed by other parts, not strictly needed here now
from typing import Optional, List, Dict, Tuple, Any

from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

# Use new locations
from bot.utils import is_valid_youtube_url
from bot.services.youtube_service import YouTubeService
from bot.exceptions import ServiceError
# --- Corrected Import Path ---
from bot.presentation.keyboard import create_quality_options_keyboard
# -----------------------------

logger = logging.getLogger(__name__)

YOUTUBE_URL_IN_TEXT_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/[\w\-/?=&#%]+")

# --- Helper to find URL ---
def find_youtube_url_in_message(message: Optional[Message]) -> Optional[str]:
    if not message: return None
    text_to_check = message.text or message.caption or ""
    match = YOUTUBE_URL_IN_TEXT_REGEX.search(text_to_check)
    if match: url = match.group(0); return url if is_valid_youtube_url(url) else None
    return None
# --------------------------

# --- Helper to process formats ---
# (Keep the simplified process_formats function here)
def process_formats(formats: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
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
# ---------------------------------


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages, detects URLs, fetches info, and sends options."""
    if not update.message or not context.bot: return
    trigger_message: Message = update.message
    url_to_process: Optional[str] = None

    # Find URL
    if update.message.reply_to_message:
        url_to_process = find_youtube_url_in_message(update.message.reply_to_message)
    if not url_to_process:
        url_to_process = find_youtube_url_in_message(update.message)

    if not url_to_process:
        return # Exit silently if no URL

    logger.info(f"Found URL: {url_to_process}. Processing request...")
    status_message = None
    chat_id = trigger_message.chat_id
    youtube_service = YouTubeService()

    try:
        status_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Processing YouTube link...")
        await asyncio.sleep(0.5)

        video_details = await youtube_service.get_video_details(url_to_process)
        title = video_details['title']
        duration = video_details['duration']
        formats = video_details['formats']

        if duration and duration > 3600:
             await status_message.edit_text("❌ Video is too long (> 1 hour).")
             return

        if not formats:
             await status_message.edit_text("❌ Could not find download formats.")
             return

        quality_options, best_quality_option = process_formats(formats)
        if best_quality_option.get('height', 0) == 0 and not quality_options:
             await status_message.edit_text("❌ No suitable video formats found.")
             return

        caption = f"🎬 **{title}**\n\nSelect download quality:"
        # Uses the correctly imported keyboard function
        keyboard = create_quality_options_keyboard(url_to_process, quality_options, best_quality_option)
        await status_message.edit_text(
             text=caption, parse_mode=ParseMode.MARKDOWN,
             reply_markup=keyboard, disable_web_page_preview=True
        )

    except (ServiceError, Exception) as e:
        logger.error(f"Error handling message for URL {url_to_process}: {e}", exc_info=(not isinstance(e, ServiceError)))
        error_text = f"❌ Error: {e}"
        if status_message:
            try: await status_message.edit_text(error_text[:4000])
            except Exception: logger.error("Failed to edit status message with error.")
        else:
            await trigger_message.reply_text(error_text[:4000], quote=True)


# Define filters for message handlers
url_message_filter = filters.TEXT & ~filters.COMMAND & ~filters.REPLY
reply_filter = filters.REPLY & ~filters.COMMAND # Handle any reply

# Create handlers
url_message_handler = MessageHandler(url_message_filter, handle_message)
reply_handler = MessageHandler(reply_filter, handle_message)

# List of message handlers to register in main.py
message_handlers = [url_message_handler, reply_handler]
