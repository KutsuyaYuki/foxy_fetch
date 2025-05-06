import asyncio
import logging
import os
from typing import Optional

from telegram import Update, InputFile
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, NetworkError

# Use new locations
from bot.config import MAX_UPLOAD_SIZE_BYTES
from bot.services.youtube_service import YouTubeService
from bot.exceptions import DownloaderError, ConversionError, ServiceError
from bot.handlers.status_updater import StatusUpdater # Import StatusUpdater
from bot.utils import cleanup_file

logger = logging.getLogger(__name__)

async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses for quality/GIF options."""
    query = update.callback_query
    await query.answer()
    if not query.data or not query.message or not context.bot: return

    chat_id = query.message.chat_id
    status_message_id = query.message.message_id # ID of the message with buttons
    bot = context.bot
    loop = asyncio.get_running_loop()

    # --- Parse callback data ---
    try:
        action_part, url = query.data.split(":", 1)
        if not action_part.startswith("q_"): raise ValueError("Invalid prefix")
        quality_selector = action_part[2:]
    except ValueError:
        logger.error(f"Invalid callback data: {query.data}")
        # Edit status message directly here, no StatusUpdater needed yet
        await context.bot.edit_message_text("❌ Invalid request.", chat_id=chat_id, message_id=status_message_id)
        return
    # -------------------------

    # --- Instantiate StatusUpdater for this request ---
    status_updater = StatusUpdater(bot, chat_id, status_message_id, loop)
    # -----------------------------------------------

    youtube_service = YouTubeService()
    final_media_path: Optional[str] = None # Define before try block

    try:
        # --- Call the service to download/convert (runs in background) ---
        # The service now handles the initial status update and progress hook wiring
        final_media_path, file_title, choice_description = await youtube_service.process_and_download(
            url=url,
            quality_selector=quality_selector,
            progress_callback=status_updater.update_progress, # Pass method for yt-dlp hook
            status_callback=status_updater.update_status      # Pass method for general status
        )
        # --- Download/Conversion finished ---

        status_updater.update_status("✅ Processing complete! Preparing upload...")

        # --- Check final file and size ---
        if not final_media_path or not os.path.exists(final_media_path):
             raise ServiceError("Processed media file not found.") # Raise error handled below

        file_size = os.path.getsize(final_media_path)
        base_filename = os.path.basename(final_media_path)
        caption = f"{file_title}\n\nQuality: {choice_description}\nSource: {url}"

        if file_size > MAX_UPLOAD_SIZE_BYTES:
            max_mb = MAX_UPLOAD_SIZE_BYTES / (1024*1024)
            size_error_text = f"❌ File too large ({file_size / (1024*1024):.2f} MB). Max: {max_mb:.0f} MB."
            logger.warning(f"File {final_media_path} too large ({file_size} bytes).")
            status_updater.update_status(size_error_text) # Update final status
            # Cleanup handled in finally block
            return # Stop processing
        # -----------------------------------

        status_updater.update_status("⬆️ Uploading to Telegram...")

        # --- Select upload method and arguments ---
        upload_method = None
        send_args = { "chat_id": chat_id, "caption": caption }
        # Use increased timeouts specifically for GIF uploads
        gif_timeouts = {
            'read_timeout': 600.0, 'write_timeout': 600.0, 'connect_timeout': 30.0
        }

        if quality_selector == 'audio':
            upload_method = bot.send_audio; send_args['audio'] = None; send_args['title'] = file_title
        elif quality_selector == 'gif':
            upload_method = bot.send_animation; send_args['animation'] = None
            send_args.update(gif_timeouts) # Add specific timeouts for GIF
        else: # Video
            upload_method = bot.send_video; send_args['video'] = None

        # --- Perform Upload ---
        if upload_method:
            with open(final_media_path, 'rb') as f:
                input_file = InputFile(f, filename=base_filename)
                # Add InputFile to arguments
                if 'audio' in send_args: send_args['audio'] = input_file
                elif 'video' in send_args: send_args['video'] = input_file
                elif 'animation' in send_args: send_args['animation'] = input_file

                await upload_method(**send_args) # Perform upload
        else:
             raise ServiceError(f"No upload method determined for selector {quality_selector}.")
        # ----------------------

        # --- Success: Delete status message ---
        try:
            await asyncio.sleep(0.5) # Brief delay
            await bot.delete_message(chat_id=chat_id, message_id=status_message_id)
            logger.info(f"Successfully processed and deleted status message {status_message_id}")
        except TelegramError as del_e:
            logger.warning(f"Could not delete status message {status_message_id}: {del_e}")
            # If delete fails, edit to final success message as fallback
            status_updater.update_status("🎉 File sent successfully!")
        # ------------------------------------

    except (DownloaderError, ConversionError, ServiceError, FileNotFoundError) as e:
        logger.error(f"Handled error during callback processing for {url}, selector {quality_selector}: {e}")
        status_updater.update_status(f"❌ Failed: {e}") # Show error in status message
    except TelegramError as e: # Catch upload errors etc.
        logger.error(f"TelegramError during callback processing: {e}")
        error_text = f"❌ Telegram Error: {e.message}"
        if isinstance(e, NetworkError) and "timed out" in str(e).lower():
            timeout = send_args.get('read_timeout', 'default') # Check if specific timeout was set
            error_text = f"❌ Upload failed: Connection timed out (limit: {timeout}s)."
        status_updater.update_status(error_text)
    except Exception as e:
        logger.exception(f"Unexpected error handling callback for {url}, selector {quality_selector}")
        status_updater.update_status("❌ An unexpected error occurred.")
    finally:
        # Ensure final media file is cleaned up if it exists
        if final_media_path and os.path.exists(final_media_path):
            cleanup_file(final_media_path)

# Handler registration
callback_handler = CallbackQueryHandler(handle_download_callback, pattern=r"^q_.*")

# List of callback handlers to register
callback_handlers = [callback_handler]
