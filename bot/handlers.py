import logging
import os
import asyncio
import re
# Make sure httpx is imported if you plan to use httpx.Timeout, otherwise just use float for timeouts
import httpx
from typing import Optional, List, Dict, Any, Tuple

from telegram import Update, InputFile, InlineKeyboardMarkup, CallbackQuery, Bot, Message
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, NetworkError # Import NetworkError
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from .config import MAX_UPLOAD_SIZE_BYTES
from .utils import is_valid_youtube_url, cleanup_file
from .keyboard import create_quality_options_keyboard, format_filesize
from .downloader import get_video_info, download_media, convert_to_gif, DownloaderError, ConversionError # Import converter

logger = logging.getLogger(__name__)

YOUTUBE_URL_IN_TEXT_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/[\w\-/?=&#%]+")

# --- Constants for GIF Upload Timeouts (in seconds) ---
GIF_UPLOAD_READ_TIMEOUT = 600.0 # 10 minutes
GIF_UPLOAD_WRITE_TIMEOUT = 600.0 # 10 minutes
GIF_UPLOAD_CONNECT_TIMEOUT = 30.0 # Slightly longer connect timeout just in case

# find_youtube_url_in_message (no change)
def find_youtube_url_in_message(message: Optional[Message]) -> Optional[str]:
    if not message: return None
    text_to_check = message.text or message.caption or ""
    match = YOUTUBE_URL_IN_TEXT_REGEX.search(text_to_check)
    if match: url = match.group(0); return url if is_valid_youtube_url(url) else None
    return None

# _edit_message_or_caption (no change)
async def _edit_message_or_caption(
    bot: Bot, chat_id: int, message_id: int, text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.MARKDOWN
) -> None:
    # (Keep implementation from previous step)
    try:
        current_parse_mode = parse_mode
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup, parse_mode=current_parse_mode)
    except BadRequest as e:
        if "message has no text" in str(e).lower() or "there is no text" in str(e).lower():
            try:
                current_parse_mode = parse_mode
                await bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup, parse_mode=current_parse_mode)
            except BadRequest as cap_e:
                if "message is not modified" in str(cap_e).lower(): logger.debug("Caption not modified")
                else: logger.error(f"BadRequest editing caption (fallback): {cap_e}")
        elif "message is not modified" in str(e).lower(): logger.debug("Text not modified")
        elif "can't parse entities" in str(e).lower() and parse_mode is not None:
            logger.warning(f"Parse entity error editing. Retrying without formatting. Error: {e}")
            try: await _edit_message_or_caption(bot, chat_id, message_id, text, reply_markup, parse_mode=None)
            except Exception as retry_e: logger.error(f"Retry editing failed. Error: {retry_e}")
        else: logger.error(f"BadRequest editing message text: {e}")
    except TelegramError as e:
        if "message to edit not found" in str(e).lower(): logger.error(f"Msg not found for editing {message_id}")
        else: logger.error(f"TelegramError editing message: {e}")
    except Exception as e: logger.error(f"Unexpected error editing message: {e}")

# start_command (no change)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (Keep implementation)
    user = update.effective_user
    if not update.message or not user: return
    await update.message.reply_html(rf"Hi {user.mention_html()}! Send me a YouTube link (or reply) and I'll help you download it.",)

# process_formats (use simplified version without size)
def process_formats(formats: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # (Use the simplified version from the previous "remove size" step)
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
    if best_overall_format_data: best_option_for_keyboard = best_overall_format_data.copy(); best_option_for_keyboard['selector'] = 'best'; logger.info(f"Determined best quality as {best_height}p")
    else: best_option_for_keyboard = {'height': 0, 'selector': 'best', 'preference': -1}; logger.warning("Could not determine best format.")
    quality_options_for_keyboard = list(available_options.values())
    sorted_options = sorted(quality_options_for_keyboard, key=lambda x: x['height'], reverse=True)
    log_options = [o.get('selector') for o in sorted_options]; log_best = best_option_for_keyboard.get('selector')
    logger.info(f"Final Keyboard Quality Options: {log_options}. Best Option: {log_best}")
    return sorted_options, best_option_for_keyboard

# initiate_download_process (no change)
async def initiate_download_process(url: str, trigger_message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (Keep implementation - calls updated process_formats/keyboard)
    if not context.bot: logger.error("Bot context missing"); await trigger_message.reply_text("Internal error."); return
    status_message = None; chat_id = trigger_message.chat_id
    try:
        status_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Processing YouTube link...")
        if not status_message: logger.error("Failed send status message."); await trigger_message.reply_text("Failed send status message."); return
        await asyncio.sleep(0.5)
        video_info = await get_video_info(url); title = video_info.get('title', 'Unknown Title'); duration = video_info.get('duration', 0)
        if duration > 3600: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text="❌ Video > 1 hour."); return
        formats = video_info.get('formats', [])
        if not formats: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text="❌ No formats found."); return
        quality_options, best_quality_option = process_formats(formats)
        if best_quality_option.get('height', 0) == 0 and not quality_options: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text="❌ No suitable formats."); return
        caption = f"🎬 **{title}**\n\nSelect download quality:"
        keyboard = create_quality_options_keyboard(url, quality_options, best_quality_option)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard, disable_web_page_preview=True)
    except DownloaderError as e: error_text = f"❌ Error processing link: {e}"; logger.error(error_text); await (status_message.edit_text(error_text) if status_message else trigger_message.reply_text(error_text))
    except TelegramError as e: logger.error(f"TelegramError initiation: {e}"); error_text = "❌ Error setting up options."; await (status_message.edit_text(error_text) if status_message and "not found" not in str(e).lower() else trigger_message.reply_text(error_text))
    except Exception as e: logger.exception(f"Unexpected error initiation: {e}"); error_text = f"❌ Unexpected error: {type(e).__name__}"; await (status_message.edit_text(error_text) if status_message else trigger_message.reply_text(error_text))


# handle_message (no change)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (Keep implementation)
    if not update.message or not context.bot: return
    url_to_process: Optional[str] = None; trigger_message: Message = update.message
    if update.message.reply_to_message: url_to_process = find_youtube_url_in_message(update.message.reply_to_message)
    if not url_to_process: url_to_process = find_youtube_url_in_message(update.message)
    if url_to_process: logger.info(f"Found URL: {url_to_process}"); await initiate_download_process(url_to_process, trigger_message, context)


# --- Updated Callback Handler for GIF ---
async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses, download, progress, CONVERSION (GIF), and upload."""
    query = update.callback_query
    await query.answer()
    if not query.data or not query.message or not context.bot: return
    chat_id = query.message.chat_id; message_id_to_edit = query.message.message_id
    bot = context.bot; loop = asyncio.get_running_loop()

    try:
        action_part, url = query.data.split(":", 1)
        if not action_part.startswith("q_"): raise ValueError("Invalid prefix")
        quality_selector = action_part[2:]
    except ValueError:
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Invalid request data.")
        return

    if quality_selector == 'audio': choice_description = "Audio Only"
    elif quality_selector == 'gif': choice_description = "GIF (Full Video)"
    elif quality_selector == 'best': choice_description = "Best Quality Video"
    elif quality_selector.startswith('h') and quality_selector[1:].isdigit(): choice_description = f"{quality_selector[1:]}p Video"
    else: choice_description = "Selected Quality"

    def sync_update_status(text: str, cb_loop: asyncio.AbstractEventLoop) -> None:
        edit_coro = _edit_message_or_caption(bot, chat_id, message_id_to_edit, text, parse_mode=None)
        asyncio.run_coroutine_threadsafe(edit_coro, cb_loop)

    status_text = f"🚀 Starting download ({choice_description})... 0%"
    await _edit_message_or_caption(bot, chat_id, message_id_to_edit, status_text)

    downloaded_video_path: str | None = None
    final_media_path: str | None = None # Holds path to video, audio, OR gif

    try:
        downloaded_video_path, file_title = await download_media(url, quality_selector, sync_update_status, loop)
        final_media_path = downloaded_video_path # Default

        if quality_selector == 'gif':
            await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "⏳ Converting to GIF (this may take a while)...")
            try:
                final_media_path = await convert_to_gif(downloaded_video_path)
                logger.info(f"GIF conversion successful: {final_media_path}")
                cleanup_file(downloaded_video_path); downloaded_video_path = None
            except ConversionError as conv_e:
                await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ GIF conversion failed: {conv_e}")
                return
            except Exception as e:
                 await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Unexpected error during GIF conversion.")
                 return

        upload_status_text = "✅ Processing complete! Preparing upload..."
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, upload_status_text)

        if not final_media_path or not os.path.exists(final_media_path):
             await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Processed file not found.")
             return

        file_size = os.path.getsize(final_media_path)
        base_filename = os.path.basename(final_media_path)
        caption = f"{file_title}\n\nQuality: {choice_description}\nSource: {url}"

        if file_size > MAX_UPLOAD_SIZE_BYTES:
            max_mb = MAX_UPLOAD_SIZE_BYTES / (1024*1024)
            size_error_text = f"❌ File too large ({file_size / (1024*1024):.2f} MB). Max: {max_mb:.0f} MB."
            await _edit_message_or_caption(bot, chat_id, message_id_to_edit, size_error_text)
            return

        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "⬆️ Uploading to Telegram...")

        upload_method = None
        # Base arguments, timeouts added conditionally
        send_args = { "chat_id": chat_id, "caption": caption }

        if quality_selector == 'audio':
            upload_method = bot.send_audio
            send_args['audio'] = None; send_args['title'] = file_title
        elif quality_selector == 'gif':
            upload_method = bot.send_animation
            send_args['animation'] = None
            # --- Apply specific timeouts for GIF upload ---
            logger.info(f"Applying increased timeouts for GIF upload: R={GIF_UPLOAD_READ_TIMEOUT}s, W={GIF_UPLOAD_WRITE_TIMEOUT}s")
            send_args['read_timeout'] = GIF_UPLOAD_READ_TIMEOUT
            send_args['write_timeout'] = GIF_UPLOAD_WRITE_TIMEOUT
            send_args['connect_timeout'] = GIF_UPLOAD_CONNECT_TIMEOUT
            # --------------------------------------------
        else: # Video
            upload_method = bot.send_video
            send_args['video'] = None

        if upload_method:
            # Open file and pass InputFile with specific timeouts if needed
            with open(final_media_path, 'rb') as f:
                input_file = InputFile(f, filename=base_filename)
                if 'audio' in send_args: send_args['audio'] = input_file
                elif 'video' in send_args: send_args['video'] = input_file
                elif 'animation' in send_args: send_args['animation'] = input_file

                # Call the upload method with potentially modified timeouts
                await upload_method(**send_args)
        else:
             await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Internal error.")
             return

        try:
             await asyncio.sleep(0.5)
             await bot.delete_message(chat_id=chat_id, message_id=message_id_to_edit)
        except TelegramError as e:
             await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "🎉 File sent successfully!")

    except (DownloaderError, ConversionError) as e:
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Failed: {e}")
    except TelegramError as e:
        logger.error(f"TelegramError during processing/upload: {e}")
        # Handle timeout specifically
        if isinstance(e, NetworkError) and "timed out" in str(e).lower():
            error_text = f"❌ Upload failed: The connection timed out (limit: {send_args.get('read_timeout', 'default')}s). Your local server might be slow or the file is very large."
        elif "file is too big" in str(e).lower() or "request entity too large" in str(e).lower():
             f_size_mb = -1.0
             if final_media_path and os.path.exists(final_media_path): f_size_mb = os.path.getsize(final_media_path) / (1024*1024)
             error_text = f"❌ Upload failed: File too large ({f_size_mb:.2f} MB)."
        else: error_text = f"❌ Upload failed: {e.message}"
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, error_text)
    except FileNotFoundError: await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Processed file not found.")
    except Exception as e:
        logger.exception(f"Unexpected error handling callback: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Unexpected error.")
    finally:
        # Cleanup both potential files
        if downloaded_video_path and os.path.exists(downloaded_video_path): cleanup_file(downloaded_video_path)
        if final_media_path and final_media_path != downloaded_video_path and os.path.exists(final_media_path): cleanup_file(final_media_path)

# Handlers list (no change)
handlers = [
    CommandHandler(["start", "help"], start_command),
    MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.REPLY, handle_message),
    MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_message),
    MessageHandler(filters.REPLY & ~filters.COMMAND & ~filters.TEXT, handle_message),
    CallbackQueryHandler(handle_download_callback, pattern=r"^q_.*")
]
