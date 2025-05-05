import logging
import os
import asyncio
import re
import httpx
from typing import Optional
from telegram import Update, InputFile, InlineKeyboardMarkup, CallbackQuery, Bot, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import TelegramError, BadRequest

# Import the upload size limit from config
from .config import MAX_UPLOAD_SIZE_BYTES
from .utils import is_valid_youtube_url, cleanup_file
from .keyboard import create_download_options_keyboard
from .downloader import get_video_info, download_media, DownloaderError

logger = logging.getLogger(__name__)

# MAX_FILE_SIZE_BYTES is now imported from config
# REMOVED: MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
YOUTUBE_URL_IN_TEXT_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/[\w\-/?=&#%]+")

# find_youtube_url_in_message (no change)
# ... (keep function as is) ...
def find_youtube_url_in_message(message: Optional[Message]) -> Optional[str]:
    if not message: return None
    text_to_check = message.text or message.caption or ""
    match = YOUTUBE_URL_IN_TEXT_REGEX.search(text_to_check)
    if match:
        url = match.group(0)
        if is_valid_youtube_url(url): return url
    return None

# _edit_message_or_caption (no change)
# ... (keep function as is) ...
async def _edit_message_or_caption(
    bot: Bot, chat_id: int, message_id: int, text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.MARKDOWN
) -> None:
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            reply_markup=reply_markup, parse_mode=parse_mode
        )
    except BadRequest as e:
        if "message has no text" in str(e).lower() or "there is no text" in str(e).lower():
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=message_id, caption=text,
                    reply_markup=reply_markup, parse_mode=parse_mode
                )
            except BadRequest as cap_e:
                if "message is not modified" in str(cap_e).lower(): logger.debug(f"Caption not modified: {text[:50]}...")
                else: logger.error(f"BadRequest editing caption (fallback): {cap_e} - Text: {text[:50]}...")
        elif "message is not modified" in str(e).lower(): logger.debug(f"Text not modified: {text[:50]}...")
        else: logger.error(f"BadRequest editing message text: {e} - Text: {text[:50]}...")
    except TelegramError as e:
        if "message to edit not found" in str(e).lower(): logger.error(f"TelegramError: Message {message_id} not found for editing. Text: {text[:50]}...")
        else: logger.error(f"TelegramError editing message: {e} - Text: {text[:50]}...")
    except Exception as e: logger.error(f"Unexpected error editing message/caption: {e} - Text: {text[:50]}...")


# start_command (no change)
# ... (keep function as is) ...
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not update.message or not user: return
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Send me a YouTube link (or reply to a previous download/link) and I'll help you download it.",
    )

# initiate_download_process (no change)
# ... (keep function as is) ...
async def initiate_download_process(
    url: str, trigger_message: Message, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.bot:
         logger.error("Bot context not found in initiate_download_process")
         await trigger_message.reply_text("An internal error occurred (Bot context missing).")
         return
    status_message = None
    chat_id = trigger_message.chat_id
    try:
        status_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Processing YouTube link...")
        if not status_message:
             logger.error("Failed to send initial status message.")
             await trigger_message.reply_text("Failed to send status message.")
             return
        await asyncio.sleep(0.5)
        video_info = await get_video_info(url)
        title = video_info.get('title', 'Unknown Title')
        duration = video_info.get('duration', 0)
        if duration > 3600:
             await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text="❌ Video is too long (max 1 hour). Please choose a shorter video.")
             return
        caption = f"🎬 **{title}**\n\nSelect a download format:"
        keyboard = create_download_options_keyboard(url)
        await context.bot.edit_message_text(
             chat_id=chat_id, message_id=status_message.message_id, text=caption,
             parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard, disable_web_page_preview=True
        )
    except DownloaderError as e:
         error_text = f"❌ Error processing link: {e}"
         if status_message: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=error_text)
         else: await trigger_message.reply_text(error_text)
    except TelegramError as e:
         logger.error(f"TelegramError during download initiation for {url}: {e}")
         error_text = "❌ An error occurred setting up download options."
         if status_message and "message to edit not found" not in str(e).lower():
             try: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=error_text)
             except TelegramError: logger.error(f"Failed to edit status message {status_message.message_id} after TelegramError.")
         else: await trigger_message.reply_text(error_text)
    except Exception as e:
        logger.exception(f"Unexpected error initiating download for URL {url}: {e}")
        error_text = "❌ An unexpected error occurred."
        if status_message:
             try: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=error_text)
             except TelegramError: logger.error(f"Failed to edit status message {status_message.message_id} after unexpected error.")
        else: await trigger_message.reply_text(error_text)

# handle_message (no change)
# ... (keep function as is) ...
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not context.bot: return
    url_to_process: Optional[str] = None
    trigger_message: Message = update.message
    if update.message.reply_to_message:
        logger.info("Message is a reply. Checking replied message for URL.")
        url_to_process = find_youtube_url_in_message(update.message.reply_to_message)
        if url_to_process: logger.info(f"Found URL in replied message: {url_to_process}")
        else: logger.info("No valid YouTube URL found in the replied message.")
    if not url_to_process:
        logger.info("Checking current message for URL.")
        url_to_process = find_youtube_url_in_message(update.message)
        if url_to_process: logger.info(f"Found URL in current message: {url_to_process}")
    if url_to_process:
        await initiate_download_process(url_to_process, trigger_message, context)


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses, download, progress, and upload, respecting configured size limits."""
    query = update.callback_query
    await query.answer()

    if not query.data or not query.message or not context.bot:
        logger.warning("Callback query missing data, message, or bot context.")
        return

    chat_id = query.message.chat_id
    message_id_to_edit = query.message.message_id
    bot = context.bot
    loop = asyncio.get_running_loop()

    try:
        action, url = query.data.split(":", 1)
    except ValueError:
        logger.error(f"Invalid callback data format: {query.data}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Invalid request.")
        return

    if not action.startswith("download_"):
        logger.warning(f"Unknown callback action: {action}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Unknown action.")
        return

    format_choice = action.replace("download_", "")

    # --- Define sync callback CLOSURE capturing necessary variables ---
    def sync_update_status(text: str, cb_loop: asyncio.AbstractEventLoop) -> None:
        # --- Disable Markdown parsing for progress updates ---
        edit_coro = _edit_message_or_caption(bot, chat_id, message_id_to_edit, text, parse_mode=None)
        # -----------------------------------------------------
        asyncio.run_coroutine_threadsafe(edit_coro, cb_loop)
    # ---------------------------------------------------------------

    # Initial status update (keeps default parse mode)
    status_text = f"🚀 Starting download ({format_choice.replace('_', ' ')})... 0%"
    await _edit_message_or_caption(bot, chat_id, message_id_to_edit, status_text)

    file_path: str | None = None
    try:
        # Pass the callback and the loop to the downloader
        file_path, file_title = await download_media(url, format_choice, sync_update_status, loop)

        # Subsequent status updates (Markdown OK here)
        upload_status_text = "✅ Download complete! Preparing upload..."
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, upload_status_text)

        file_size = os.path.getsize(file_path)
        base_filename = os.path.basename(file_path)
        caption = f"{file_title}\n\nSource: {url}"

        if file_size > MAX_UPLOAD_SIZE_BYTES:
            max_mb = MAX_UPLOAD_SIZE_BYTES / (1024*1024)
            size_error_text = f"❌ Download complete, but the file is too large ({file_size / (1024*1024):.2f} MB). Maximum upload size is {max_mb:.0f} MB."
            logger.warning(f"File {file_path} too large ({file_size} bytes) for upload limit {MAX_UPLOAD_SIZE_BYTES}.")
            await _edit_message_or_caption(bot, chat_id, message_id_to_edit, size_error_text)
            return

        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "⬆️ Uploading to Telegram...", reply_markup=None) # Parse mode default (Markdown) ok

        upload_method = None
        send_args = { "chat_id": chat_id, "caption": caption }

        if format_choice == 'audio_only':
            upload_method = bot.send_audio
            send_args['audio'] = None
        else:
            upload_method = bot.send_video
            send_args['video'] = None

        if upload_method:
            # Set potentially longer timeouts specifically for the upload request
            upload_timeout = httpx.Timeout(300.0) # 5 minutes, adjust as needed
            with open(file_path, 'rb') as file_content:
                 input_file = InputFile(file_content, filename=base_filename)
                 if 'audio' in send_args: send_args['audio'] = input_file
                 elif 'video' in send_args: send_args['video'] = input_file

                 # Pass timeout to the specific upload call
                 send_args['write_timeout'] = upload_timeout.write # Separate write timeout
                 send_args['read_timeout'] = upload_timeout.read  # Separate read timeout
                 send_args['connect_timeout'] = upload_timeout.connect # Connect timeout

                 await upload_method(**send_args)
        else:
             logger.error("No valid upload method determined (internal logic error).")
             await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Internal error: Could not determine upload method.")
             return

        # Delete the status message after successful upload
        try:
             await asyncio.sleep(0.5)
             await bot.delete_message(chat_id=chat_id, message_id=message_id_to_edit)
             logger.info(f"Successfully deleted status message {message_id_to_edit} in chat {chat_id}")
        except TelegramError as e:
             logger.warning(f"Could not delete status message {message_id_to_edit} after success: {e}")
             await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "🎉 File sent successfully!")


    # Exception handling remains the same
    except DownloaderError as e:
        logger.error(f"DownloaderError for callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Download failed: {e}")
    except TelegramError as e: # Catch upload errors
        logger.error(f"TelegramError during upload for callback {query.data}: {e}")
        if isinstance(e, NetworkError) and "timed out" in str(e).lower():
            error_text = f"❌ Upload failed: The connection timed out. Your local server might be too slow or the file is very large."
        elif "file is too big" in str(e).lower() or "request entity too large" in str(e).lower():
             # This shouldn't happen with the pre-check, but handle defensively
             f_size_mb = -1.0
             if file_path and os.path.exists(file_path): f_size_mb = os.path.getsize(file_path) / (1024*1024)
             error_text = f"❌ Upload failed: File too large ({f_size_mb:.2f} MB)."
        else:
            error_text = f"❌ Failed to upload: {e.message}"
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, error_text)
    except FileNotFoundError:
        logger.error(f"FileNotFoundError after download for callback {query.data}. Path: {file_path}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Downloaded file not found.")
    except Exception as e:
        logger.exception(f"Unexpected error handling callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ An unexpected error occurred.")
    finally:
        if file_path and os.path.exists(file_path):
             cleanup_file(file_path)



# Handlers list (no change)
handlers = [
    CommandHandler(["start", "help"], start_command),
    MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.REPLY, handle_message),
    MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_message),
    MessageHandler(filters.REPLY & ~filters.COMMAND & ~filters.TEXT, handle_message),
    CallbackQueryHandler(handle_download_callback, pattern=r"^download_.*")
]
