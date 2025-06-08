import asyncio
import logging
import os
from typing import Optional, Dict, Any, BinaryIO

from telegram import Update, InputFile
from telegram.ext import CallbackQueryHandler
from telegram.error import TelegramError, BadRequest, NetworkError

from bot.config import MAX_UPLOAD_SIZE_BYTES
from bot.services.youtube_service import YouTubeService
from bot.exceptions import DownloaderError, ConversionError, ServiceError
from bot.handlers.status_updater import StatusUpdater
from bot.helpers import cleanup_file, get_platform_name
from bot.context import CustomContext
from .utils import parse_download_callback

logger = logging.getLogger(__name__)

async def handle_download_callback(update: Update, context: CustomContext) -> None:
    """Handle download quality selection callbacks."""
    query = update.callback_query
    user = update.effective_user

    if not query or not query.message or not context.bot or not query.data or not user:
        logger.warning("Download callback received invalid data or missing components.")
        if query:
            await query.answer("Invalid request.", show_alert=True)
        return

    db_manager = context.db_manager
    await query.answer()

    # Initialize variables
    interaction_id: Optional[int] = None
    final_media_path: Optional[str] = None
    download_record_id: Optional[int] = None
    media_file_handle: Optional[BinaryIO] = None
    url_to_process: Optional[str] = None
    status_updater: Optional[StatusUpdater] = None

    try:
        # Log user interaction
        await _log_user_interaction(db_manager, user, query)
        interaction_id = await _log_callback_interaction(db_manager, user, query)

        # Parse callback data
        parsed_data = parse_download_callback(query.data)
        if not parsed_data:
            await _handle_invalid_callback(context.bot, query)
            return

        quality_selector, url_to_process = parsed_data

        # Initialize components
        chat_id = query.message.chat_id
        status_message_id = query.message.message_id
        status_updater = StatusUpdater(context.bot, chat_id, status_message_id, asyncio.get_running_loop())
        youtube_service = YouTubeService(db_manager)

        # Create download record
        download_record_id = await _create_download_record(
            db_manager, user.id, url_to_process, quality_selector, interaction_id
        )
        if not download_record_id:
            status_updater.update_status("❌ Internal error: Failed to track download ID.")
            return

        # Process and download
        final_media_path, file_title, choice_description = await youtube_service.process_and_download(
            url=url_to_process,
            quality_selector=quality_selector,
            download_record_id=download_record_id,
            progress_callback=status_updater.update_progress,
            status_callback=status_updater.update_status
        )

        # Upload file
        await _upload_media_file(
            context.bot, chat_id, final_media_path, file_title,
            choice_description, url_to_process, quality_selector,
            db_manager, download_record_id, status_updater
        )

        # Clean up status message
        await _cleanup_status_message(context.bot, chat_id, status_message_id, user.id)

    except (DownloaderError, ConversionError, ServiceError, FileNotFoundError) as e:
        await _handle_service_error(e, download_record_id, db_manager, status_updater, user.id, url_to_process)
    except TelegramError as te:
        await _handle_telegram_error(te, download_record_id, db_manager, status_updater, user.id)
    except Exception as e:
        await _handle_unexpected_error(e, download_record_id, db_manager, status_updater, user.id, url_to_process)
    finally:
        await _cleanup_resources(media_file_handle, final_media_path)

# Helper functions
async def _log_user_interaction(db_manager, user, query):
    """Log user information."""
    await db_manager.upsert_user(
        user_id=user.id, username=user.username,
        first_name=user.first_name, last_name=user.last_name
    )

async def _log_callback_interaction(db_manager, user, query) -> Optional[int]:
    """Log callback interaction and return interaction ID."""
    return await db_manager.log_interaction(
        user_id=user.id, chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        interaction_type='callback_query', content=query.data
    )

async def _handle_invalid_callback(bot, query):
    """Handle invalid callback data."""
    logger.error(f"Invalid download callback data: {query.data}")
    try:
        await bot.edit_message_text(
            "❌ Invalid request format.",
            chat_id=query.message.chat_id,
            message_id=query.message.message_id
        )
    except (TelegramError, BadRequest):
        pass

async def _create_download_record(db_manager, user_id, url, quality_selector, interaction_id) -> Optional[int]:
    """Create download record and return record ID."""
    try:
        platform_name = get_platform_name(url)
        return await db_manager.create_download_record(
            user_id=user_id, video_url=url,
            selected_quality=quality_selector, platform=platform_name,
            interaction_id=interaction_id
        )
    except Exception as e:
        logger.error(f"Failed to create download record for user {user_id}, URL {url}: {e}", exc_info=True)
        return None

async def _upload_media_file(bot, chat_id, file_path, title, description, url, quality_selector, db_manager, record_id, status_updater):
    """Handle media file upload."""
    if not file_path or not os.path.exists(file_path):
        raise ServiceError("Processed media file not found after download/conversion.")

    file_size = os.path.getsize(file_path)
    caption = f"{title}\n\nQuality: {description}\nSource: {url}"

    if file_size > MAX_UPLOAD_SIZE_BYTES:
        max_mb = MAX_UPLOAD_SIZE_BYTES / (1024*1024)
        size_error_text = f"❌ File too large ({file_size / (1024*1024):.2f} MB). Max: {max_mb:.0f} MB."
        await db_manager.update_download_status(record_id, 'failed',
            error_message=f"File too large ({file_size} bytes)", file_size=file_size)
        status_updater.update_status(size_error_text)
        return

    await db_manager.update_download_status(record_id, 'upload_started')
    status_updater.update_status("⬆️ Uploading to Telegram...")

    # Determine upload method and arguments
    upload_method, send_args = _get_upload_method_and_args(
        bot, chat_id, file_path, title, caption, quality_selector
    )

    if upload_method:
        await upload_method(**send_args)
        await db_manager.update_download_status(record_id, 'completed', file_size=file_size)
        logger.info(f"Upload successful for record {record_id}")
    else:
        raise ServiceError(f"No upload method determined for selector '{quality_selector}'.")

def _get_upload_method_and_args(bot, chat_id, file_path, title, caption, quality_selector):
    """Get the appropriate upload method and arguments."""
    base_filename = os.path.basename(file_path)
    media_file_handle = open(file_path, 'rb')
    input_file = InputFile(media_file_handle, filename=base_filename)

    send_args = {"chat_id": chat_id, "caption": caption}

    if quality_selector == 'audio':
        return bot.send_audio, {**send_args, 'audio': input_file, 'title': title}
    elif quality_selector == 'gif':
        return bot.send_animation, {**send_args, 'animation': input_file}
    else:
        return bot.send_video, {**send_args, 'video': input_file}

async def _cleanup_status_message(bot, chat_id, message_id, user_id):
    """Clean up the status message."""
    try:
        await asyncio.sleep(0.5)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted status message {message_id} for user {user_id}")
    except TelegramError as del_e:
        logger.warning(f"Could not delete status message {message_id}: {del_e}")

async def _handle_service_error(error, record_id, db_manager, status_updater, user_id, url):
    """Handle service-related errors."""
    err_msg = f"❌ Failed: {error}"
    logger.error(f"Handled error for {url or 'N/A'}, user {user_id}: {error}",
                exc_info=isinstance(error, ServiceError))
    if record_id:
        await db_manager.update_download_status(record_id, 'failed', error_message=str(error))
    if status_updater:
        status_updater.update_status(err_msg)

async def _handle_telegram_error(error, record_id, db_manager, status_updater, user_id):
    """Handle Telegram API errors."""
    logger.error(f"TelegramError during callback for user {user_id}: {error}", exc_info=True)
    error_text = f"❌ Telegram Error: {error.message}"
    if isinstance(error, NetworkError) and "timed out" in str(error).lower():
        error_text = "❌ Upload failed: Connection timed out."
    if record_id:
        await db_manager.update_download_status(record_id, 'failed', error_message=f"TelegramError: {error.message}")
    if status_updater:
        status_updater.update_status(error_text)

async def _handle_unexpected_error(error, record_id, db_manager, status_updater, user_id, url):
    """Handle unexpected errors."""
    logger.exception(f"Unexpected error in download callback for {url or 'N/A'}, user {user_id}")
    if record_id:
        await db_manager.update_download_status(record_id, 'failed', error_message=f"Unexpected error: {type(error).__name__}")
    if status_updater:
        status_updater.update_status("❌ An unexpected error occurred.")

async def _cleanup_resources(media_file_handle, final_media_path):
    """Clean up file handles and temporary files."""
    if media_file_handle and not media_file_handle.closed:
        try:
            media_file_handle.close()
            logger.debug(f"Closed media file handle")
        except Exception as e:
            logger.error(f"Error closing media file handle: {e}", exc_info=True)

    if final_media_path and os.path.exists(final_media_path):
        cleanup_file(final_media_path)

download_callback_handler = CallbackQueryHandler(handle_download_callback, pattern=r"^q_.*")
