import logging
import os
from typing import Optional
from telegram import Update, InputFile, InlineKeyboardMarkup, CallbackQuery
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import TelegramError, BadRequest

from .utils import is_valid_youtube_url, cleanup_file
from .keyboard import create_download_options_keyboard
from .downloader import get_video_info, download_media, DownloaderError

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024 # Telegram Bot API limit (50 MB)

async def _edit_message_or_caption(query: CallbackQuery, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, parse_mode: Optional[str] = ParseMode.MARKDOWN) -> None:
    """
    Helper function to edit message text or caption, gracefully handling
    BadRequest errors like 'message is not modified'.
    """
    try:
        if query.message.text is not None: # Check if text exists (even if empty)
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif query.message.caption is not None: # Check if caption exists
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            # Fallback if somehow the message has neither (shouldn't happen with current logic)
            logger.warning("Attempted to edit message with no text or caption. Message ID: %s", query.message.message_id)
            # Optionally send a new message as fallback
            # await query.message.reply_text(text, parse_mode=parse_mode)
    except BadRequest as e:
        # Ignore common "message is not modified" error, log others
        if "message is not modified" in str(e).lower():
             logger.info(f"Message not modified: {text[:50]}...") # Log snippet
        else:
             logger.error(f"BadRequest editing message/caption: {e} - Text: {text[:50]}...")
             # Consider notifying the user with a new message if editing fails unexpectedly
             # await query.message.reply_text(f"Error updating status: {e}")
    except Exception as e:
        logger.error(f"Unexpected error editing message/caption: {e} - Text: {text[:50]}...")
        # Consider notifying the user
        # await query.message.reply_text(f"Error updating status: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start or /help command is issued."""
    user = update.effective_user
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
    processing_message = await update.message.reply_text("⏳ Processing YouTube link...")

    try:
        video_info = await get_video_info(url)
        title = video_info.get('title', 'Unknown Title')
        duration = video_info.get('duration', 0)
        thumbnail_url = video_info.get('thumbnail') # Get thumbnail URL

        # Basic check for excessively long videos (optional, adjust as needed)
        if duration > 3600: # e.g., limit to 1 hour
            await processing_message.edit_text("❌ Video is too long (max 1 hour). Please choose a shorter video.")
            return

        caption = f"🎬 **{title}**\n\nSelect a download format:"
        keyboard = create_download_options_keyboard(url)

        # Try sending with thumbnail, fallback to text only
        if thumbnail_url:
             try:
                 # Attempt to delete "Processing..." message *before* sending photo
                 try:
                     await processing_message.delete()
                 except BadRequest as e:
                     # Ignore if message already deleted or cannot be deleted
                     logger.warning(f"Could not delete processing message: {e}")

                 await update.message.reply_photo(
                      photo=thumbnail_url,
                      caption=caption,
                      parse_mode=ParseMode.MARKDOWN,
                      reply_markup=keyboard
                 )
             except TelegramError as e:
                 logger.warning(f"Failed to send photo for {url}: {e}. Falling back to text.")
                 # If sending photo fails, we need to edit the original 'processing_message'
                 await processing_message.edit_text(
                    caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                 )
        else:
             # If no thumbnail, just edit the 'processing_message'
             await processing_message.edit_text(
                  caption,
                  parse_mode=ParseMode.MARKDOWN,
                  reply_markup=keyboard,
                  disable_web_page_preview=True
             )

    except DownloaderError as e:
        await processing_message.edit_text(f"❌ Error processing link: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error handling message for URL {url}: {e}")
        await processing_message.edit_text("❌ An unexpected error occurred. Please try again later.")


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses for download options."""
    query = update.callback_query
    await query.answer() # Acknowledge callback

    if not query.data or not query.message:
        logger.warning("Received callback query with no data or message.")
        return

    try:
        action, url = query.data.split(":", 1)
    except ValueError:
        logger.error(f"Invalid callback data format: {query.data}")
        await _edit_message_or_caption(query, "❌ Error: Invalid request.", reply_markup=None)
        return

    if not action.startswith("download_"):
        logger.warning(f"Unknown callback action: {action}")
        await _edit_message_or_caption(query, "❌ Error: Unknown action.", reply_markup=None)
        return

    format_choice = action.replace("download_", "") # e.g., 'video_audio', 'audio_only'

    # Edit the message (text or caption) to show download is starting, remove keyboard
    status_text = f"🚀 Starting download ({format_choice.replace('_', ' ')})... Please wait."
    await _edit_message_or_caption(query, status_text, reply_markup=None) # Remove keyboard

    file_path: str | None = None
    try:
        file_path, file_title = await download_media(url, format_choice)

        # Check file size before attempting upload
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            size_error_text = f"❌ Download complete, but the file ({file_size / (1024*1024):.2f} MB) is too large for Telegram (max 50 MB)."
            await _edit_message_or_caption(query, size_error_text, reply_markup=None)
            cleanup_file(file_path) # Clean up the oversized file
            return

        await _edit_message_or_caption(query, "✅ Download complete! Uploading to Telegram...", reply_markup=None)

        # Upload the file
        chat_id = query.message.chat_id
        base_filename = os.path.basename(file_path)
        caption = f"{file_title}" # Use video title as caption

        with open(file_path, 'rb') as file_content:
            input_file = InputFile(file_content, filename=base_filename)
            if format_choice == 'audio_only':
                await context.bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption, title=file_title)
            else: # video_audio or video_only
                await context.bot.send_video(chat_id=chat_id, video=input_file, caption=caption)

        await _edit_message_or_caption(query, "🎉 File sent successfully!", reply_markup=None)
        # Optional: Delete the message containing status updates after success
        # try:
        #    await query.delete_message()
        # except BadRequest as e:
        #    logger.warning(f"Could not delete status message after success: {e}")


    except DownloaderError as e:
        logger.error(f"DownloaderError for callback {query.data}: {e}")
        await _edit_message_or_caption(query, f"❌ Download failed: {e}", reply_markup=None)
    except TelegramError as e:
        logger.error(f"TelegramError during upload for callback {query.data}: {e}")
        await _edit_message_or_caption(query, f"❌ Failed to upload file to Telegram: {e.message}. It might be too large or another issue occurred.", reply_markup=None)
    except FileNotFoundError:
        logger.error(f"FileNotFoundError after download for callback {query.data}. Expected path: {file_path}")
        await _edit_message_or_caption(query, "❌ Error: Downloaded file not found. Please try again.", reply_markup=None)
    except Exception as e:
        logger.exception(f"Unexpected error handling callback {query.data}: {e}")
        await _edit_message_or_caption(query, "❌ An unexpected error occurred during download or upload.", reply_markup=None)
    finally:
        # Ensure cleanup happens even if upload fails or file is oversized
        if file_path:
            cleanup_file(file_path)


# Handlers list
handlers = [
    CommandHandler(["start", "help"], start_command),
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
    CallbackQueryHandler(handle_download_callback, pattern=r"^download_.*")
]
