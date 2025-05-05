import logging
import os
import asyncio # Import asyncio
from typing import Optional
from telegram import Update, InputFile, InlineKeyboardMarkup, CallbackQuery, Bot
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import TelegramError, BadRequest

from .utils import is_valid_youtube_url, cleanup_file
from .keyboard import create_download_options_keyboard
from .downloader import get_video_info, download_media, DownloaderError # Keep this import

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Keep this helper function here
async def _edit_message_or_caption(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.MARKDOWN
) -> None:
    """
    Helper function to edit message text or caption, called via run_coroutine_threadsafe.
    Gracefully handles BadRequest errors like 'message is not modified'.
    """
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
        logger.error(f"TelegramError editing message: {e} - Text: {text[:50]}...")
    except Exception as e:
        logger.error(f"Unexpected error editing message/caption: {e} - Text: {text[:50]}...")


# start_command and handle_message remain unchanged from the previous version
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start or /help command is issued."""
    user = update.effective_user
    if not update.message or not user: return
    await update.message.reply_html(
        rf"Hi {user.mention_html()}! Send me a YouTube link and I'll help you download it.",
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles non-command messages, checking for YouTube URLs."""
    if not update.message or not update.message.text:
        return # Ignore updates without messages or text

    message_text = update.message.text

    if not is_valid_youtube_url(message_text):
        await update.message.reply_text("Please send a valid YouTube URL.")
        return

    url = message_text
    try:
        processing_message = await update.message.reply_text("⏳ Processing YouTube link...")
        if not processing_message:
             logger.error("Failed to send 'Processing...' message.")
             return
    except TelegramError as e:
        logger.error(f"Failed to send initial processing message: {e}")
        return


    try:
        video_info = await get_video_info(url)
        title = video_info.get('title', 'Unknown Title')
        duration = video_info.get('duration', 0)
        thumbnail_url = video_info.get('thumbnail')

        if duration > 3600:
             await processing_message.edit_text("❌ Video is too long (max 1 hour). Please choose a shorter video.")
             return


        caption = f"🎬 **{title}**\n\nSelect a download format:"
        keyboard = create_download_options_keyboard(url)

        if thumbnail_url:
             try:
                  await processing_message.delete()
                  await update.message.reply_photo(
                       photo=thumbnail_url,
                       caption=caption,
                       parse_mode=ParseMode.MARKDOWN,
                       reply_markup=keyboard
                  )
             except TelegramError as e:
                  logger.warning(f"Failed to send photo for {url}: {e}. Falling back to text.")
                  await processing_message.edit_text(
                     caption,
                     parse_mode=ParseMode.MARKDOWN,
                     reply_markup=keyboard,
                     disable_web_page_preview=True
                  )
        else:
             await processing_message.edit_text(
                  caption,
                  parse_mode=ParseMode.MARKDOWN,
                  reply_markup=keyboard,
                  disable_web_page_preview=True
             )

    except DownloaderError as e:
         await processing_message.edit_text(f"❌ Error processing link: {e}")
    except TelegramError as e:
         logger.error(f"TelegramError during message handling setup for {url}: {e}")
         try:
             await processing_message.edit_text("❌ An error occurred setting up download options.")
         except TelegramError:
              logger.error("Failed even to edit processing message after earlier TelegramError.")
    except Exception as e:
        logger.exception(f"Unexpected error handling message for URL {url}: {e}")
        try:
            await processing_message.edit_text("❌ An unexpected error occurred. Please try again later.")
        except TelegramError:
             logger.error("Failed to edit processing message after unexpected error.")


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses for download options."""
    query = update.callback_query
    await query.answer()

    if not query.data or not query.message or not context.bot:
        logger.warning("Received callback query with missing data, message or bot context.")
        return

    chat_id = query.message.chat_id
    message_id_to_edit = query.message.message_id # The message ID we will edit and finally delete
    bot = context.bot # Get bot instance

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

    # --- Define the Synchronous Callback for Progress Updates ---
    def sync_update_status(text: str) -> None:
        loop = asyncio.get_running_loop()
        edit_coro = _edit_message_or_caption(bot, chat_id, message_id_to_edit, text, None)
        asyncio.run_coroutine_threadsafe(edit_coro, loop)
    # -----------------------------------------------------------

    # Initial status update using the async helper directly
    status_text = f"🚀 Starting download ({format_choice.replace('_', ' ')})... 0%"
    await _edit_message_or_caption(bot, chat_id, message_id_to_edit, status_text, reply_markup=None)

    file_path: str | None = None
    try:
        # --- Pass the synchronous callback to the downloader ---
        file_path, file_title = await download_media(url, format_choice, sync_update_status)
        # --------------------------------------------------

        # Final status updates after download completes
        upload_status_text = "✅ Download complete! Uploading to Telegram..."
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, upload_status_text, reply_markup=None)

        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            size_error_text = f"❌ Download complete, but the file ({file_size / (1024*1024):.2f} MB) is too large for Telegram (max 50 MB)."
            await _edit_message_or_caption(bot, chat_id, message_id_to_edit, size_error_text, reply_markup=None)
            # File is too large, DO NOT delete the status message, cleanup file and return
            cleanup_file(file_path)
            return

        base_filename = os.path.basename(file_path)
        caption = f"{file_title}"

        with open(file_path, 'rb') as file_content:
            input_file = InputFile(file_content, filename=base_filename)
            if format_choice == 'audio_only':
                await bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption, title=file_title)
            else:
                await bot.send_video(chat_id=chat_id, video=input_file, caption=caption)


        # --- Delete the status message after successful upload ---
        try:
             final_status_text = "🎉 File sent successfully! Cleaning up..."
             await _edit_message_or_caption(bot, chat_id, message_id_to_edit, final_status_text, reply_markup=None)
             # Add a small delay so the user can see the final status briefly
             await asyncio.sleep(1.5)
             await bot.delete_message(chat_id=chat_id, message_id=message_id_to_edit)
             logger.info(f"Successfully deleted status message {message_id_to_edit} in chat {chat_id}")
        except TelegramError as e:
             logger.warning(f"Could not delete status message {message_id_to_edit} after success: {e}")
             # If deletion fails, it's not critical, just log it.
        # -------------------------------------------------------


    except DownloaderError as e:
        logger.error(f"DownloaderError for callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Download failed: {e}", reply_markup=None)
        # Do not delete message on error
    except TelegramError as e:
        logger.error(f"TelegramError during upload/final status for callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, f"❌ Failed to upload or update status: {e.message}", reply_markup=None)
        # Do not delete message on error
    except FileNotFoundError:
        logger.error(f"FileNotFoundError after download for callback {query.data}. Expected path: {file_path}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ Error: Downloaded file not found.", reply_markup=None)
        # Do not delete message on error
    except Exception as e:
        logger.exception(f"Unexpected error handling callback {query.data}: {e}")
        await _edit_message_or_caption(bot, chat_id, message_id_to_edit, "❌ An unexpected error occurred.", reply_markup=None)
        # Do not delete message on error
    finally:
        # Cleanup happens regardless of success *unless* file was too large (cleaned above)
        if file_path and os.path.exists(file_path): # Check exists as it might have been cleaned already
             cleanup_file(file_path)



handlers = [
    CommandHandler(["start", "help"], start_command),
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
    CallbackQueryHandler(handle_download_callback, pattern=r"^download_.*")
]
