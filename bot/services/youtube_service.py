import asyncio
import logging
import os
from typing import Dict, Optional, Tuple, Any, Callable

from bot.exceptions import DownloaderError, ConversionError, ServiceError
from bot.external.downloader import get_video_info, download_media
from bot.external.ffmpeg_processor import convert_to_gif
from bot.helpers import cleanup_file
from bot.database import DatabaseManager # Import DatabaseManager for type hinting

logger = logging.getLogger(__name__)

class YouTubeService:
    """Orchestrates YouTube processing: info fetching, downloading, conversion."""

    def __init__(self, db_manager: DatabaseManager): # Accept DatabaseManager instance
        self._db_manager = db_manager

    async def get_video_details(self, url: str) -> Dict[str, Any]:
        """Fetches video info (title, duration, formats)."""
        try:
            info_dict = await get_video_info(url)
            return {
                'title': info_dict.get('title', 'Unknown Title'),
                'duration': info_dict.get('duration'), # Can be None
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
        download_record_id: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None
        ) -> Tuple[str, str, str]:
        """
        Downloads the video/audio, potentially converts to GIF, reports progress,
        and updates the download record using the internal DatabaseManager.
        Returns: (final_media_path, video_title, choice_description)
        """
        downloaded_path: Optional[str] = None
        final_media_path: Optional[str] = None
        video_title: str = "Unknown Title"

        if quality_selector == 'audio': choice_description = "Audio Only"
        elif quality_selector == 'gif': choice_description = "GIF (Full Video)"
        elif quality_selector == 'best': choice_description = "Best Quality Video"
        elif quality_selector.startswith('h') and quality_selector[1:].isdigit():
            choice_description = f"{quality_selector[1:]}p Video"
        else:
            choice_description = "Selected Quality" # Fallback

        try:
            if status_callback: status_callback(f"🚀 Starting download ({choice_description})...")
            await self._db_manager.update_download_status(download_record_id, 'download_started')

            downloaded_path, video_title = await download_media(
                url, quality_selector, progress_hook=progress_callback
            )
            await self._db_manager.set_download_title(download_record_id, video_title)
            final_media_path = downloaded_path # Initially, final path is the downloaded path

            if quality_selector == 'gif':
                if status_callback: status_callback("⏳ Converting to GIF...")
                await self._db_manager.update_download_status(download_record_id, 'conversion_started')
                try:
                    # Status 'converting' implies the process is ongoing
                    # We update to 'converting' before the actual conversion attempt.
                    # If convert_to_gif fails, the handler will set to 'failed'.
                    # If successful, the handler will set to 'upload_started' or 'completed'.
                    # No specific 'converted' status is strictly needed if followed by upload.
                    await self._db_manager.update_download_status(download_record_id, 'converting')

                    gif_path = await convert_to_gif(downloaded_path)
                    logger.info(f"GIF conversion successful: {gif_path} for record {download_record_id}")
                    final_media_path = gif_path # Update final_media_path to the new GIF path
                    cleanup_file(downloaded_path) # Clean up original video used for GIF
                    downloaded_path = None # Original video is no longer needed
                except (ConversionError, FileNotFoundError) as conv_e:
                    logger.error(f"GIF conversion failed for record {download_record_id}: {conv_e}")
                    # Error will be re-raised and handled by the calling handler, which updates DB status
                    raise
                except Exception as e: # Catch any other unexpected error during conversion
                    logger.exception(f"Unexpected error during GIF conversion for record {download_record_id}")
                    raise ConversionError(f"Unexpected GIF conversion error: {type(e).__name__}") from e

            if not final_media_path or not os.path.exists(final_media_path):
                # This state implies something went wrong if final_media_path is not set or file is missing
                # The handler will catch this and update DB status to 'failed'.
                raise ServiceError(f"Processed media file not found for record {download_record_id}.")

            logger.info(f"Processing complete for record {download_record_id}. Final path: {final_media_path}")
            # The status is implicitly 'info_fetched' or 'downloading' or 'converting' here.
            # The calling handler will update to 'upload_started' then 'completed' or 'failed'.
            return final_media_path, video_title, choice_description

        except (DownloaderError, ConversionError, ServiceError) as e: # Re-raise these specific errors
            logger.error(f"Service error for record {download_record_id}, URL {url}: {e}", exc_info=isinstance(e, ServiceError))
            # Cleanup potentially created files
            if downloaded_path and os.path.exists(downloaded_path): cleanup_file(downloaded_path)
            # If final_media_path is different (e.g. GIF) and exists, clean it too on error
            if final_media_path and final_media_path != downloaded_path and os.path.exists(final_media_path):
                cleanup_file(final_media_path)
            raise # Re-raise for the handler to set DB status to 'failed'
        except Exception as e: # Catch any other unexpected error
            logger.exception(f"Unexpected service error for record {download_record_id}, URL {url}")
            if downloaded_path and os.path.exists(downloaded_path): cleanup_file(downloaded_path)
            if final_media_path and final_media_path != downloaded_path and os.path.exists(final_media_path):
                cleanup_file(final_media_path)
            # Wrap in ServiceError before re-raising
            raise ServiceError(f"An unexpected error occurred during processing: {type(e).__name__}") from e
