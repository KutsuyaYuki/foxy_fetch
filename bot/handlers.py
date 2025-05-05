import logging
import os
import asyncio
import re
from typing import Optional
from telegram import Update, InputFile, InlineKeyboardMarkup, CallbackQuery, Bot, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import TelegramError, BadRequest

from .utils import is_valid_youtube_url, cleanup_file
from .keyboard import create_download_options_keyboard
from .downloader import get_video_info, download_media, DownloaderError

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
YOUTUBE_URL_IN_TEXT_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/[\w\-/?=&#%]+")

def find_youtube_url_in_message(message: Optional[Message]) -> Optional[str]:
    # (Keep implementation from previous step)
    if not message:
        return None
    text_to_check = message.text or message.caption or ""
    match = YOUTUBE_URL_IN_TEXT_REGEX.search(text_to_check)
    if match:
        url = match.group(0)
        if is_valid_youtube_url(url):
            return url
    return None

async def _edit_message_or_caption(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.MARKDOWN
) -> None:
    # (Keep implementation from previous step)
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        if "message has no text" in str(e).lower() or "there is no text" in str(e).lower():
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            except BadRequest as cap_e:
                if "message is not modified" in str(cap_e).lower():
                    logger.debug(f"Caption not modified: {text[:50]}...")
                else:
                    logger.error(f"BadRequest editing caption (fallback): {cap_e} - Text: {text[:50]}...")
        elif "message is not modified" in str(e).lower():
             logger.debug(f"Text not modified: {text[:50]}...")
        else:
             logger.error(f"BadRequest editing message text: {e} - Text: {text[:50]}...")
    except TelegramError as e:
        # Handle 'message to edit not found' specifically if needed, though it shouldn't happen now
        if "message to edit not found" in str(e).lower():
             logger.error(f"TelegramError: Message {message_id} not found for editing. Text: {text[:50]}...")
        else:
             logger.error(f"TelegramError editing message: {e} - Text: {text[:50]}...")
    except Exception as e:
        logger.error(f"Unexpected error editing message/caption: {e} - Text: {text[:50]}...")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (Keep implementation from previous step)
    user = update.effective_user
    if not update.message or not user: return
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Send me a YouTube link (or reply to a previous download/link) and I'll help you download it.",
    )

# --- Updated Download Initiation Logic ---
async def initiate_download_process(
    url: str,
    trigger_message: Message, # The user's message that triggered this
    context: ContextTypes.DEFAULT_TYPE
    ) -> None:
    """Sends a status message, fetches video info, and edits the status message with options."""
    if not context.bot:
         logger.error("Bot context not found in initiate_download_process")
         await trigger_message.reply_text("An internal error occurred (Bot context missing).")
         return

    status_message = None # Message used for status updates
    chat_id = trigger_message.chat_id

    try:
        # Send a *new* message for status updates, not as a reply initially
        status_message = await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ Processing YouTube link..."
            # Optional: reply_to_message_id=trigger_message.message_id if preferred
        )
        if not status_message:
             logger.error("Failed to send initial status message.")
             await trigger_message.reply_text("Failed to send status message.") # Inform user
             return

        # Wait briefly to ensure message exists before editing
        await asyncio.sleep(0.5)

        video_info = await get_video_info(url)
        title = video_info.get('title', 'Unknown Title')
        duration = video_info.get('duration', 0)
        # We won't use thumbnail directly in the status message to simplify editing
        # thumbnail_url = video_info.get('thumbnail')

        if duration > 3600:
             await context.bot.edit_message_text(
                 chat_id=chat_id,
                 message_id=status_message.message_id,
                 text="❌ Video is too long (max 1 hour). Please choose a shorter video."
             )
             return

        caption = f"🎬 **{title}**\n\nSelect a download format:"
        keyboard = create_download_options_keyboard(url) # Pass the confirmed URL

        # Edit the status message to show options
        await context.bot.edit_message_text(
             chat_id=chat_id,
             message_id=status_message.message_id,
             text=caption,
             parse_mode=ParseMode.MARKDOWN,
             reply_markup=keyboard,
             disable_web_page_preview=True
        )

    except DownloaderError as e:
         error_text = f"❌ Error processing link: {e}"
         if status_message:
             await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=error_text)
         else: # If sending initial message failed
             await trigger_message.reply_text(error_text)
    except TelegramError as e:
         logger.error(f"TelegramError during download initiation for {url}: {e}")
         error_text = "❌ An error occurred setting up download options."
         if status_message and "message to edit not found" not in str(e).lower(): # Avoid edit error loop
             try: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=error_text)
             except TelegramError: logger.error(f"Failed to edit status message {status_message.message_id} after TelegramError.")
         else: # If sending failed or edit failed because msg not found
             await trigger_message.reply_text(error_text)
    except Exception as e:
        logger.exception(f"Unexpected error initiating download for URL {url}: {e}")
        error_text = "❌ An unexpected error occurred."
        if status_message:
             try: await context.bot.edit_message_text(chat_id=chat_id, message_id=status_message.message_id, text=error_text)
             except TelegramError: logger.error(f"Failed to edit status message {status_message.message_id} after unexpected error.")
        else:
             await trigger_message.reply_text(error_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (Keep implementation from previous step)
    if not update.message or not context.bot:
        return

    url_to_process: Optional[str] = None
    # The message that triggered the bot (contains URL or is a reply)
    trigger_message: Message = update.message

    if update.message.reply_to_message:
        logger.info("Message is a reply. Checking replied message for URL.")
        url_to_process = find_youtube_url_in_message(update.message.reply_to_message)
        if url_to_process:
            logger.info(f"Found URL in replied message: {url_to_process}")
            # Keep trigger_message as the user's reply
        else:
             logger.info("No valid YouTube URL found in the replied message.")

    if not url_to_process:
        logger.info("Checking current message for URL.")
        url_to_process = find_youtube_url_in_message(update.message)
        if url_to_process:
             logger.info(f"Found URL in current message: {url_to_process}")
             # Keep trigger_message as the user's direct message
        # else: logger.info("No actionable YouTube URL found.") # No URL found anywhere


    if url_to_process:
        # Pass the user's trigger message
        await initiate_download_process(url_to_process, trigger_message, context)


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (Mostly same as previous version, slight change in send_x call)
    query = update.callback_query
    await query.answer()

    if not query.data or not query.message or not context.bot:
        logger.warning("Received callback query with missing data, message or bot context.")
        return

    chat_id = query.message.chat_id
    # This is the message ID of the status message (sent by initiate_download_process)
    message_id_to_edit = query.message.message_id
    bot = context.bot

    try:
        action, url = query.data.split(":", 1)
    except ValueError:
        logger.error(f"Invalid callback data format: {query.data}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Invalid request.", reply_markup=None)
        return

    if not action.startswith("download_"):
        logger.warning(f"Unknown callback action: {action}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Unknown action.", reply_markup=None)
        return

    format_choice = action.replace("download_", "")

    def sync_update_status(text: str) -> None:
        loop = asyncio.get_running_loop()
        # Edit the status message
        edit_coro = _edit_message_or_caption(bot, chat_id, message_id_to_edit, text, None)
        asyncio.run_coroutine_threadsafe(edit_coro, loop)

    status_text = f"🚀 Starting download ({format_choice.replace('_', ' ')})... 0%"
    await _edit_message_or_caption(bot, chat_id, message_id_to_edit, status_text, reply_markup=None)

    file_path: str | None = None
    try:
        file_path, file_title = await download_media(url, format_choice, sync_update_status)

        upload_status_text = "✅ Download complete! Uploading to Telegram..."
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, upload_status_text, reply_markup=None)

        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            size_error_text = f"❌ Download complete, but the file ({file_size / (1024*1024):.2f} MB) is too large for Telegram (max 50 MB)."
            await _edit_message_or_caption(bot, chat_id, message_id_to_edit, size_error_text, reply_markup=None)
            cleanup_file(file_path)
            return # Keep status message visible with error

        base_filename = os.path.basename(file_path)
        caption = f"{file_title}\n\nSource: {url}"

        # Send the file without replying to the status message
        # Replying to the original user message is complex to track here, so send directly
        with open(file_path, 'rb') as file_content:
            input_file = InputFile(file_content, filename=base_filename)
            send_args = {
                 "chat_id": chat_id,
                 "caption": caption,
                 # Removed reply_to_message_id for simplicity
            }

            if format_choice == 'audio_only':
                await bot.send_audio(audio=input_file, **send_args)
            else:
                await bot.send_video(video=input_file, **send_args)

        # Delete the status message after successful upload
        try:
             # No need to edit before delete now
             await asyncio.sleep(0.5) # Brief pause before delete
             await bot.delete_message(chat_id=chat_id, message_id=message_id_to_edit)
             logger.info(f"Successfully deleted status message {message_id_to_edit} in chat {chat_id}")
        except TelegramError as e:
             logger.warning(f"Could not delete status message {message_id_to_edit} after success: {e}")


    except DownloaderError as e:
        logger.error(f"DownloaderError for callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Download failed: {e}", reply_markup=None)
    except TelegramError as e:
        logger.error(f"TelegramError during upload/final status for callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Failed to upload or update status: {e.message}", reply_markup=None)
    except FileNotFoundError:
        logger.error(f"FileNotFoundError after download for callback {query.data}. Expected path: {file_path}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Downloaded file not found.", reply_markup=None)
    except Exception as e:
        logger.exception(f"Unexpected error handling callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ An unexpected error occurred.", reply_markup=None)
    finally:
        if file_path and os.path.exists(file_path):
             cleanup_file(file_path)


# Handlers list remains the same
handlers = [
    CommandHandler(["start", "help"], start_command),
    MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.REPLY, handle_message), # Handle direct messages
    MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_message), # Handle replies containing text
    # Added handler for replies that might not have text (e.g., just replying to media)
    MessageHandler(filters.REPLY & ~filters.COMMAND & ~filters.TEXT, handle_message),
    CallbackQueryHandler(handle_download_callback, pattern=r"^download_.*")
]
