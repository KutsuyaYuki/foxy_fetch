# bot/handlers/callback_handlers.py

import asyncio
import logging
import os
import re # Added for re.fullmatch
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timedelta, timezone

from telegram import Update, InputFile, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError, BadRequest, NetworkError
from telegram.constants import ParseMode
import aiosqlite

from bot.config import MAX_UPLOAD_SIZE_BYTES, ADMIN_IDS
from bot.services.youtube_service import YouTubeService
from bot.exceptions import DownloaderError, ConversionError, ServiceError
from bot.handlers.status_updater import StatusUpdater
from bot.helpers import cleanup_file
import bot.database as db
from bot.presentation.keyboard import (
    create_stats_main_menu_keyboard,
    create_stats_submenu_keyboard
)

logger = logging.getLogger(__name__)

def parse_download_callback(data: str) -> Optional[Tuple[str, str]]: # Returns (quality_selector, final_url_to_process)
    """
    Parses callback data for download actions.
    Expected format: "q_{selector}:{payload}"
    Payload can be "id:{video_id}" or a full URL (fallback).
    Returns a tuple of (quality_selector, url_to_process) or None if invalid.
    """
    try:
        action_part, payload = data.split(":", 1)  # Split only on the first colon
        if not action_part.startswith("q_"):
            logger.warning(f"Callback data '{data}' is not a download action (no 'q_' prefix).")
            return None
        quality_selector = action_part[2:]

        if payload.startswith("id:"):
            video_id = payload[3:]
            # Basic validation for a YouTube video ID (11 characters, specific charset)
            if not re.fullmatch(r"[0-9A-Za-z_-]{11}", video_id):
                logger.error(f"Invalid video ID format '{video_id}' in callback_data payload: '{payload}'")
                return None
            reconstructed_url = f"https://www.youtube.com/watch?v={video_id}"
            logger.debug(f"Reconstructed URL '{reconstructed_url}' from ID '{video_id}' for quality '{quality_selector}'")
            return quality_selector, reconstructed_url
        else:
            # Assume it's a full URL (legacy or fallback from keyboard creation)
            if not (payload.startswith("http://") or payload.startswith("https://")):
                logger.warning(f"Callback payload '{payload}' is not a recognized ID and doesn't look like a full URL. Proceeding anyway.")
            return quality_selector, payload
    except ValueError: # Not enough parts to split (e.g., "q_best" without URL/ID)
        logger.warning(f"Could not split callback data into action and payload: '{data}'")
        return None
    except Exception as e: # Catch any other unexpected error during parsing
        logger.error(f"Unexpected error parsing download callback data '{data}': {e}", exc_info=True)
        return None

def parse_stats_callback(data: str) -> Optional[Tuple[str, str]]:
    try:
        prefix, action = data.split(":", 1)
        if prefix not in ("stats_menu", "stats_show"): return None
        return prefix, action
    except (ValueError, AttributeError):
        logger.warning(f"Could not parse stats callback data: {data}")
        return None


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not query.message or not context.bot or not query.data or not user:
        logger.warning("Download callback received invalid data or missing components.")
        if query: await query.answer("Invalid request.", show_alert=True)
        return

    db_connection: Optional[aiosqlite.Connection] = context.bot_data.get('db_connection')
    if not db_connection:
        logger.error("Database connection not found in context for handle_download_callback.")
        await query.answer("Sorry, a critical internal error occurred.", show_alert=True)
        try: await query.edit_message_text("❌ Internal Error (DB Missing). Please notify the administrator.")
        except (TelegramError, BadRequest): pass
        return

    await query.answer()

    interaction_id: Optional[int] = None
    try:
        await db.upsert_user(
            db_connection, user_id=user.id, username=user.username,
            first_name=user.first_name, last_name=user.last_name
        )
        interaction_id = await db.log_interaction(
            db_connection, user_id=user.id, chat_id=query.message.chat_id,
            message_id=query.message.message_id, interaction_type='callback_query', content=query.data
        )
        logger.debug(f"Logged download callback interaction {interaction_id} from user {user.id}")
    except Exception as e:
        logger.error(f"Database error logging download callback for user {user.id}: {e}", exc_info=True)

    parsed_data = parse_download_callback(query.data)
    if not parsed_data:
        logger.error(f"Invalid download callback data format: {query.data} from user {user.id}. Could not be parsed.")
        try:
            await context.bot.edit_message_text("❌ Invalid request format. Could not understand selection.", chat_id=query.message.chat_id, message_id=query.message.message_id)
        except (TelegramError, BadRequest):
            logger.warning(f"Failed to edit message for invalid callback data format from user {user.id}")
        return

    quality_selector, url_to_process = parsed_data # url_to_process is now the full or reconstructed URL
    chat_id = query.message.chat_id
    status_message_id = query.message.message_id
    bot = context.bot
    loop = asyncio.get_running_loop()

    status_updater = StatusUpdater(bot, chat_id, status_message_id, loop)
    youtube_service = YouTubeService()
    final_media_path: Optional[str] = None
    download_record_id: Optional[int] = None

    try:
        try:
            download_record_id = await db.create_download_record(
                db_connection, user_id=user.id, youtube_url=url_to_process, # Use url_to_process
                selected_quality=quality_selector, interaction_id=interaction_id
            )
        except Exception as e:
            logger.error(f"Failed to create download record for user {user.id}, URL {url_to_process}: {e}", exc_info=True)
            status_updater.update_status("❌ Internal error: Could not track download request.")
            return

        if not download_record_id:
            logger.error(f"Failed to get download_record_id after creation for user {user.id}, URL {url_to_process}")
            status_updater.update_status("❌ Internal error: Failed to track download ID.")
            return

        final_media_path, file_title, choice_description = await youtube_service.process_and_download(
            db_connection=db_connection, url=url_to_process, # Use url_to_process
            quality_selector=quality_selector, download_record_id=download_record_id,
            progress_callback=status_updater.update_progress, status_callback=status_updater.update_status
        )

        status_updater.update_status("✅ Processing complete! Preparing upload...")

        if not final_media_path or not os.path.exists(final_media_path):
             err_msg = "Processed media file not found after download/conversion."
             await db.update_download_status(db_connection, download_record_id, 'failed', error_message=err_msg)
             raise ServiceError(err_msg)

        file_size = os.path.getsize(final_media_path)
        base_filename = os.path.basename(final_media_path)
        caption = f"{file_title}\n\nQuality: {choice_description}\nSource: {url_to_process}" # Use url_to_process

        if file_size > MAX_UPLOAD_SIZE_BYTES:
            max_mb = MAX_UPLOAD_SIZE_BYTES / (1024*1024)
            size_error_text = f"❌ File too large ({file_size / (1024*1024):.2f} MB). Max: {max_mb:.0f} MB."
            logger.warning(f"File {final_media_path} too large ({file_size} bytes) for user {user.id}. Record ID: {download_record_id}")
            await db.update_download_status(db_connection, download_record_id, 'failed', error_message=f"File too large ({file_size} bytes)", file_size=file_size)
            status_updater.update_status(size_error_text)
            return

        await db.update_download_status(db_connection, download_record_id, 'upload_started')
        status_updater.update_status("⬆️ Uploading to Telegram...")

        upload_method = None
        send_args: Dict[str, Any] = { "chat_id": chat_id, "caption": caption }
        gif_timeouts = {'read_timeout': 600.0, 'write_timeout': 600.0, 'connect_timeout': 30.0}

        if quality_selector == 'audio':
            upload_method = bot.send_audio; send_args['audio'] = None; send_args['title'] = file_title
        elif quality_selector == 'gif':
            upload_method = bot.send_animation; send_args['animation'] = None
            send_args.update(gif_timeouts)
        else: # Video
            upload_method = bot.send_video; send_args['video'] = None

        if upload_method:
            with open(final_media_path, 'rb') as f:
                input_file = InputFile(f, filename=base_filename)
                if 'audio' in send_args: send_args['audio'] = input_file
                elif 'video' in send_args: send_args['video'] = input_file
                elif 'animation' in send_args: send_args['animation'] = input_file
                await upload_method(**send_args)
            logger.info(f"Successfully uploaded {final_media_path} for user {user.id}. Record ID: {download_record_id}")
            await db.update_download_status(db_connection, download_record_id, 'completed', file_size=file_size)
        else:
             err_msg = f"No upload method determined for selector {quality_selector}."
             await db.update_download_status(db_connection, download_record_id, 'failed', error_message=err_msg)
             raise ServiceError(err_msg)

        try:
            await asyncio.sleep(0.5)
            await bot.delete_message(chat_id=chat_id, message_id=status_message_id)
            logger.info(f"Successfully processed and deleted status message {status_message_id} for user {user.id}")
        except TelegramError as del_e:
            logger.warning(f"Could not delete status message {status_message_id}: {del_e}")
            status_updater.update_status("🎉 File sent successfully!")

    except (DownloaderError, ConversionError, ServiceError, FileNotFoundError) as e:
        err_msg = f"❌ Failed: {e}"
        logger.error(f"Handled error during callback processing for {url_to_process}, selector {quality_selector}, user {user.id}: {e}", exc_info=True)
        if download_record_id: await db.update_download_status(db_connection, download_record_id, 'failed', error_message=str(e))
        status_updater.update_status(err_msg)
    except TelegramError as e:
        logger.error(f"TelegramError during callback processing for user {user.id}: {e}", exc_info=True)
        error_text = f"❌ Telegram Error: {e.message}"
        if isinstance(e, NetworkError) and "timed out" in str(e).lower():
            timeout = send_args.get('read_timeout', 'default')
            error_text = f"❌ Upload failed: Connection timed out (limit: {timeout}s)."
        if download_record_id: await db.update_download_status(db_connection, download_record_id, 'failed', error_message=f"TelegramError: {e.message}")
        status_updater.update_status(error_text)
    except Exception as e:
        logger.exception(f"Unexpected error handling callback for {url_to_process}, selector {quality_selector}, user {user.id}")
        if download_record_id: await db.update_download_status(db_connection, download_record_id, 'failed', error_message=f"Unexpected error: {type(e).__name__}")
        status_updater.update_status("❌ An unexpected error occurred.")
    finally:
        if final_media_path and os.path.exists(final_media_path):
            cleanup_file(final_media_path)


async def handle_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses for the statistics interface (admin only)."""
    query = update.callback_query
    user = update.effective_user
    if not query or not query.message or not query.data or not user:
        logger.warning("Stats callback received invalid data or missing components.")
        if query: await query.answer("Invalid request.", show_alert=True)
        return

    db_connection: Optional[aiosqlite.Connection] = context.bot_data.get('db_connection')
    if not db_connection:
        logger.error("Database connection not found in context for handle_stats_callback.")
        await query.answer("Sorry, a critical internal error occurred.", show_alert=True)
        try: await query.edit_message_text("❌ Internal Error (DB Missing). Please notify the administrator.")
        except (TelegramError, BadRequest): pass
        return

    if user.id not in ADMIN_IDS:
        logger.warning(f"Non-admin user {user.id} tried to use stats callback: {query.data}")
        await query.answer("Access Denied.", show_alert=True)
        return

    await query.answer()

    try:
        await db.log_interaction(
            db_connection, user_id=user.id, chat_id=query.message.chat_id,
            message_id=query.message.message_id, interaction_type='callback_query', content=query.data
        )
    except Exception as e:
        logger.error(f"Database error logging stats callback for admin {user.id}: {e}", exc_info=True)

    parsed_data = parse_stats_callback(query.data)
    if not parsed_data:
        logger.error(f"Invalid stats callback data format: {query.data} from admin {user.id}")
        try: await query.edit_message_text("❌ Invalid stats request format.")
        except (TelegramError, BadRequest): pass
        return

    menu_type, action = parsed_data
    text = "📊 *Bot Statistics*\n\n"
    keyboard: Optional[InlineKeyboardMarkup] = None
    now = datetime.now(timezone.utc)
    one_day_ago_iso = (now - timedelta(days=1)).isoformat()
    seven_days_ago_iso = (now - timedelta(days=7)).isoformat()

    try:
        if menu_type == "stats_menu":
            if action == "main":
                text += "Select a category:"
                keyboard = create_stats_main_menu_keyboard()
            elif action == "users":
                text += "👤 *User Statistics*\nSelect an option:"
                keyboard = create_stats_submenu_keyboard("users")
            elif action == "interactions":
                text += "💬 *Interaction Statistics*\nSelect an option:"
                keyboard = create_stats_submenu_keyboard("interactions")
            elif action == "downloads":
                text += "📥 *Download Statistics*\nSelect an option:"
                keyboard = create_stats_submenu_keyboard("downloads")
            else:
                 logger.warning(f"Unknown stats menu action: {action}")
                 text += "Unknown menu."
                 keyboard = create_stats_main_menu_keyboard()

        elif menu_type == "stats_show":
            if action == "summary":
                total_users = await db.get_total_user_count(db_connection)
                active_24h = await db.get_users_count(db_connection, one_day_ago_iso)
                status_counts = await db.get_download_status_counts(db_connection)
                completed_downloads = status_counts.get('completed', 0)
                failed_downloads = status_counts.get('failed', 0)
                total_dl_attempts = sum(status_counts.values())
                success_rate = (completed_downloads / total_dl_attempts * 100) if total_dl_attempts > 0 else 0

                text += "📊 *Overall Summary*\n"
                text += f"- Total Users: `{total_users}`\n"
                text += f"- Active Users (24h): `{active_24h}`\n"
                text += f"- Total Download Attempts: `{total_dl_attempts}`\n"
                text += f"- Completed Downloads: `{completed_downloads}` ✅\n"
                text += f"- Failed Downloads: `{failed_downloads}` ❌\n"
                text += f"- Success Rate: `{success_rate:.2f}%`\n"
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="stats_menu:main")]])

            elif action == "users_total":
                count = await db.get_total_user_count(db_connection)
                text += f"👤 Total Unique Users: `{count}`"
                keyboard = create_stats_submenu_keyboard("users")
            elif action == "users_active_24h":
                count = await db.get_users_count(db_connection, one_day_ago_iso)
                text += f"👤 Active Users (last 24h): `{count}`"
                keyboard = create_stats_submenu_keyboard("users")
            elif action == "users_active_7d":
                count = await db.get_users_count(db_connection, seven_days_ago_iso)
                text += f"👤 Active Users (last 7 days): `{count}`"
                keyboard = create_stats_submenu_keyboard("users")

            elif action == "interactions_by_type":
                counts = await db.get_interaction_count_by_type(db_connection)
                text += "💬 *Interactions by Type (All Time)*\n"
                if counts:
                    for type_name, count_val in sorted(counts.items()): # Renamed count to count_val
                        text += f"- {type_name.replace('_', ' ').title()}: `{count_val}`\n"
                else:
                    text += "_No interactions recorded._\n"
                keyboard = create_stats_submenu_keyboard("interactions")
            elif action == "interactions_24h":
                counts = await db.get_interaction_count_by_type(db_connection, since_iso_timestamp=one_day_ago_iso)
                text += "💬 *Interactions by Type (Last 24h)*\n"
                if counts:
                    for type_name, count_val in sorted(counts.items()): # Renamed count to count_val
                        text += f"- {type_name.replace('_', ' ').title()}: `{count_val}`\n"
                else:
                    text += "_No interactions in the last 24 hours._\n"
                keyboard = create_stats_submenu_keyboard("interactions")

            elif action == "downloads_by_status":
                counts = await db.get_download_status_counts(db_connection)
                text += "📥 *Downloads by Status (All Time)*\n"
                if counts:
                    for status_name, count_val in sorted(counts.items()): # Renamed count to count_val
                        text += f"- {status_name.title()}: `{count_val}`\n"
                else:
                    text += "_No downloads recorded._\n"
                keyboard = create_stats_submenu_keyboard("downloads")
            elif action == "downloads_by_quality":
                counts = await db.get_downloads_by_quality_summary(db_connection)
                text += "📥 *Completed Downloads by Quality*\n"
                if counts:
                    for quality_name, count_val in sorted(counts.items()): # Renamed count to count_val
                        text += f"- {quality_name.replace('h', '').upper() if quality_name.startswith('h') else quality_name.title()}: `{count_val}`\n"
                else:
                    text += "_No completed downloads recorded._\n"
                keyboard = create_stats_submenu_keyboard("downloads")
            elif action == "downloads_top_urls":
                urls = await db.get_top_requested_urls(db_connection, limit=5)
                text += "📥 *Top 5 Requested URLs*\n"
                if urls:
                    for i, (url_item, count_val) in enumerate(urls): # Renamed count to count_val
                        display_url = url_item[:60] + '...' if len(url_item) > 60 else url_item
                        text += f"{i+1}. `{display_url}` (Count: `{count_val}`)\n"
                else:
                    text += "_No URLs requested yet._\n"
                keyboard = create_stats_submenu_keyboard("downloads")
            else:
                logger.warning(f"Unknown stats show action: {action}")
                text += "Unknown statistics view."
                keyboard = create_stats_main_menu_keyboard()
        else:
            logger.error(f"Unknown stats menu type: {menu_type}")
            text = "Error: Unknown statistics menu."
            keyboard = create_stats_main_menu_keyboard()

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    except Exception as e:
        logger.exception(f"Error handling stats callback action '{action}' for admin {user.id}")
        try:
            await query.edit_message_text("❌ An error occurred while fetching statistics.")
        except (TelegramError, BadRequest):
             pass

download_callback_handler = CallbackQueryHandler(handle_download_callback, pattern=r"^q_.*")
stats_callback_handler = CallbackQueryHandler(handle_stats_callback, pattern=r"^stats_(menu|show):.*")
callback_handlers = [download_callback_handler, stats_callback_handler]
