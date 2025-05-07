import logging
import re
import asyncio
from typing import Optional, List, Dict, Tuple, Any

from telegram import Update, Message
from telegram.constants import ParseMode
from telegram.ext import MessageHandler, filters

from bot.helpers import is_valid_youtube_url
from bot.services.youtube_service import YouTubeService
from bot.exceptions import ServiceError
from bot.presentation.keyboard import create_quality_options_keyboard
from main import CustomContext # Import CustomContext for type hinting

logger = logging.getLogger(__name__)

YOUTUBE_URL_IN_TEXT_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/[\w\-/?=&#%]+")

def find_youtube_url_in_message(message: Optional[Message]) -> Optional[str]:
    if not message: return None
    text_to_check = message.text or message.caption or ""
    match = YOUTUBE_URL_IN_TEXT_REGEX.search(text_to_check)
    if match:
        url = match.group(0)
        return url if is_valid_youtube_url(url) else None
    return None

def process_formats(formats: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    available_options: Dict[int, Dict[str, Any]] = {}
    valid_vcodec_prefixes = ('avc', 'h264', 'vp9', 'av01')
    min_height = 240
    best_overall_format_data: Optional[Dict[str, Any]] = None
    best_height = 0

    for f_format in formats: # Renamed f to f_format
        if f_format.get('vcodec') == 'none' or not f_format.get('height'):
            continue
        height: int = f_format.get('height', 0)
        vcodec: str = f_format.get('vcodec', 'none').lower()

        if height < min_height or not any(vcodec.startswith(prefix) for prefix in valid_vcodec_prefixes):
            continue

        pref_val = f_format.get('preference')
        current_pref: float = float(pref_val) if isinstance(pref_val, (int, float)) else -1.0

        stored_pref: float = -1.0
        if height in available_options:
            stored_pref_val = available_options[height].get('preference')
            stored_pref = float(stored_pref_val) if isinstance(stored_pref_val, (int, float)) else -1.0

        if height not in available_options or current_pref > stored_pref:
            available_options[height] = {'height': height, 'selector': f'h{height}', 'preference': current_pref}

        current_best_pref: float = -1.0
        if best_overall_format_data:
            best_pref_val = best_overall_format_data.get('preference')
            current_best_pref = float(best_pref_val) if isinstance(best_pref_val, (int, float)) else -1.0

        if height >= best_height and (height > best_height or current_pref > current_best_pref):
            best_height = height
            best_overall_format_data = available_options[height].copy()

    if best_overall_format_data:
        best_option_for_keyboard = best_overall_format_data.copy()
        best_option_for_keyboard['selector'] = 'best'
    else:
        best_option_for_keyboard = {'height': 0, 'selector': 'best', 'preference': -1.0}
        logger.warning("Could not determine best format from provided list.")

    quality_options_for_keyboard = list(available_options.values())
    sorted_options = sorted(quality_options_for_keyboard, key=lambda x: x['height'], reverse=True)
    return sorted_options, best_option_for_keyboard


async def handle_message(update: Update, context: CustomContext) -> None: # Use CustomContext
    """Handles messages, detects URLs, fetches info, logs, and sends options."""
    if not update.message or not context.bot:
        logger.warning("Message handler received update without message or bot.")
        return

    trigger_message: Message = update.message
    user = update.effective_user
    if not user:
        logger.warning("Cannot handle message: effective_user is None.")
        return

    db_manager = context.db_manager # Access DatabaseManager via context

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

    try:
        await db_manager.upsert_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        await db_manager.log_interaction( # Log interaction_id if needed later
            user_id=user.id,
            chat_id=trigger_message.chat_id,
            message_id=trigger_message.message_id,
            interaction_type=interaction_type,
            content=trigger_message.text or trigger_message.caption or url_to_process
        )
    except ConnectionError as ce:
        logger.error(f"Database connection error during message handling for user {user.id}: {ce}")
        await trigger_message.reply_text("Sorry, a database connection error occurred. Please try again later.")
        return
    except Exception as e:
        logger.error(f"Database error logging URL interaction for user {user.id}: {e}", exc_info=True)
        # Non-critical, proceed with functionality if possible

    status_message: Optional[Message] = None
    chat_id = trigger_message.chat_id
    youtube_service = YouTubeService(db_manager) # Pass db_manager to service

    try:
        status_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Processing YouTube link...")
        await asyncio.sleep(0.1) # Brief pause for UX

        video_details = await youtube_service.get_video_details(url_to_process)
        title = video_details['title']
        duration = video_details.get('duration') # Duration can be None
        formats = video_details['formats']

        if duration and duration > 3600 * 2: # 2 hours
            logger.warning(f"Video {url_to_process} too long ({duration}s) for user {user.id}")
            if status_message: await status_message.edit_text("❌ Video is too long (> 2 hours).")
            return
        if not formats:
            logger.warning(f"Could not find formats for {url_to_process} for user {user.id}")
            if status_message: await status_message.edit_text("❌ Could not find download formats for this video.")
            return

        quality_options, best_quality_option = process_formats(formats)
        if not quality_options and (not best_quality_option or best_quality_option.get('height', 0) == 0):
            logger.warning(f"No suitable video formats found for {url_to_process} after processing for user {user.id}")
            if status_message: await status_message.edit_text("❌ No suitable video formats found (check resolution/availability).")
            return

        caption = f"🎬 **{title}**\n\nSelect download quality:"
        # video_id is extracted inside create_quality_options_keyboard
        keyboard = create_quality_options_keyboard(url_to_process, quality_options, best_quality_option)

        if status_message:
            await status_message.edit_text(
                text=caption, parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard, disable_web_page_preview=True
            )
            logger.info(f"Presented quality options for {url_to_process} to user {user.id} in message {status_message.message_id}")
        else: # Should not happen if initial send_message succeeded
            logger.error(f"Status message was None when trying to present quality options for user {user.id}")
            await trigger_message.reply_text("Error displaying options. Please try again.", quote=True)


    except ServiceError as e:
        error_text = f"❌ Error processing link: {e}"
        logger.error(f"ServiceError handling message for URL {url_to_process} from user {user.id}: {e}", exc_info=True)
        if status_message:
            try: await status_message.edit_text(error_text[:4000])
            except Exception: logger.error("Failed to edit status message with ServiceError.")
        else:
            await trigger_message.reply_text(error_text[:4000], quote=True)
    except Exception as e:
        error_text = f"❌ An unexpected error occurred: {type(e).__name__}"
        logger.exception(f"Unexpected error handling message for URL {url_to_process} from user {user.id}")
        if status_message:
            try: await status_message.edit_text(error_text)
            except Exception: logger.error("Failed to edit status message with unexpected error.")
        else:
            await trigger_message.reply_text(error_text, quote=True)


url_message_filter = filters.TEXT & ~filters.COMMAND & ~filters.REPLY
reply_filter = filters.REPLY & ~filters.COMMAND

url_message_handler = MessageHandler(url_message_filter, handle_message)
reply_handler = MessageHandler(reply_filter, handle_message)

message_handlers = [url_message_handler, reply_handler]
