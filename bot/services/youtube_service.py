import asyncio
import logging
import os
from typing import Dict, Optional, Tuple, Any, Callable, List

from bot.exceptions import DownloaderError, ConversionError, ServiceError
from bot.external.downloader import get_video_info, download_media
from bot.external.ffmpeg_processor import convert_to_gif
from bot.utils import cleanup_file
# --- Import DB functions ---
import bot.database as db
# -------------------------

logger = logging.getLogger(__name__)

class YouTubeService:
    """Orchestrates YouTube processing: info fetching, downloading, conversion."""

    async def get_video_details(self, url: str) -> Dict[str, Any]:
        """Fetches video info (title, duration, formats)."""
        try:
            # This function doesn't directly interact with a specific download_record_id yet,
            # but title could be updated to a record later if needed.
            info_dict = await get_video_info(url)
            return {
                'title': info_dict.get('title', 'Unknown Title'),
                'duration': info_dict.get('duration'),
                'formats': info_dict.get('formats', [])
            }
        except DownloaderError as e:
            logger.error(f"Service error getting video info for {url}: {e}")
            raise ServiceError(f"Failed to get video details: {e}") from e
        except Exception as e:
            logger.exception(f"Unexpected service error getting video info for {url}")
            raise ServiceError(f"Unexpected error getting video details: {type(e).__name__}")

    async def process_and_download(
        self,
        url: str,
        quality_selector: str,
        download_record_id: int, # Added to link DB record
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None
        ) -> Tuple[str, str, str]:
        """
        Downloads the video/audio, potentially converts to GIF, reports progress,
        and updates the download record in the database.
        Returns: (final_media_path, video_title, choice_description)
        """
        downloaded_path: Optional[str] = None
        final_media_path: Optional[str] = None
        video_title: str = "Unknown Title" # Default

        if quality_selector == 'audio': choice_description = "Audio Only"
        elif quality_selector == 'gif': choice_description = "GIF (Full Video)"
        elif quality_selector == 'best': choice_description = "Best Quality Video"
        elif quality_selector.startswith('h') and quality_selector[1:].isdigit(): choice_description = f"{quality_selector[1:]}p Video"
        else: choice_description = "Selected Quality" # Should not happen with current validation

        try:
            # --- Potentially fetch info again to get title if not already done, or rely on earlier fetch ---
            # For simplicity, we'll get title from download_media, but could pre-fetch.
            # await db.update_download_status(download_record_id, 'info_fetched') # If pre-fetching

            # 1. Download media
            if status_callback: status_callback(f"🚀 Starting download ({choice_description})... 0%")
            await db.update_download_status(download_record_id, 'download_started')

            # Wrap progress_callback to also update DB 'downloading' status (optional, can be frequent)
            # For now, 'download_started' covers it.
            downloaded_path, video_title = await download_media(
                url, quality_selector, progress_hook=progress_callback
            )
            # Update title in DB
            await db.set_download_title(download_record_id, video_title)
            final_media_path = downloaded_path

             # 2. Convert to GIF if requested
            if quality_selector == 'gif':
                if status_callback: status_callback("⏳ Converting to GIF...")
                await db.update_download_status(download_record_id, 'conversion_started')
                try:
                    final_media_path = await convert_to_gif(downloaded_path)
                    logger.info(f"GIF conversion successful: {final_media_path} for record {download_record_id}")
                    await db.update_download_status(download_record_id, 'converting') # Or 'conversion_completed_pre_upload'
                    cleanup_file(downloaded_path)
                    downloaded_path = None
                except (ConversionError, FileNotFoundError) as conv_e:
                    logger.error(f"GIF conversion failed for record {download_record_id}: {conv_e}")
                    # Error will be propagated and handled by caller to set 'failed' status
                    raise
                except Exception as e:
                    logger.exception(f"Unexpected error during GIF conversion for record {download_record_id}")
                    raise ConversionError(f"Unexpected GIF conversion error: {type(e).__name__}") from e

            # 3. Final checks
            if not final_media_path or not os.path.exists(final_media_path):
                # This error should be caught by the caller to update DB status to 'failed'
                raise ServiceError(f"Processed media file not found after download/conversion for record {download_record_id}.")

            # At this point, download/conversion is successful, pre-upload
            # The 'completed' status will be set by the handler *after* successful upload.
            # 'upload_started' will also be set by handler.
            logger.info(f"Processing complete for record {download_record_id}. Final path: {final_media_path}")
            return final_media_path, video_title, choice_description

        except (DownloaderError, ConversionError, ServiceError) as e:
            # These errors are specific and will be handled by the callback_handler,
            # which will then update the DB record to 'failed' with the error message.
            logger.error(f"Service error during process/download for record {download_record_id}, URL {url}: {e}")
            if downloaded_path and downloaded_path != final_media_path: cleanup_file(downloaded_path)
            if final_media_path: cleanup_file(final_media_path)
            raise # Re-raise for the handler to catch and update DB
        except Exception as e:
            logger.exception(f"Unexpected service error during process/download for record {download_record_id}, URL {url}")
            if downloaded_path: cleanup_file(downloaded_path)
            if final_media_path and final_media_path != downloaded_path: cleanup_file(final_media_path)
            raise ServiceError(f"An unexpected error occurred: {type(e).__name__}") from e
