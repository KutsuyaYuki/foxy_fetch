import asyncio
import logging
import os
from typing import Dict, Optional, Tuple, Any, Callable, List

# Use new exception locations
from bot.exceptions import DownloaderError, ConversionError, ServiceError
# Use new external module locations
from bot.external.downloader import get_video_info, download_media
from bot.external.ffmpeg_processor import convert_to_gif
from bot.utils import cleanup_file

logger = logging.getLogger(__name__)

class YouTubeService:
    """Orchestrates YouTube processing: info fetching, downloading, conversion."""

    async def get_video_details(self, url: str) -> Dict[str, Any]:
        """Fetches video info (title, duration, formats)."""
        try:
            info_dict = await get_video_info(url)
            return {
                'title': info_dict.get('title', 'Unknown Title'),
                'duration': info_dict.get('duration'),
                'formats': info_dict.get('formats', [])
            }
        except DownloaderError as e:
            logger.error(f"Service error getting video info: {e}")
            raise ServiceError(f"Failed to get video details: {e}") from e
        except Exception as e:
            logger.exception(f"Unexpected service error getting video info for {url}")
            raise ServiceError(f"Unexpected error getting video details: {type(e).__name__}")

    async def process_and_download(
        self,
        url: str,
        quality_selector: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None
        ) -> Tuple[str, str, str]:
        """
        Downloads the video/audio, potentially converts to GIF, reports progress.
        Returns: (final_media_path, video_title, choice_description)
        """
        downloaded_path: Optional[str] = None
        final_media_path: Optional[str] = None
        video_title: str = "Unknown Title"
        loop = asyncio.get_running_loop()

        # Determine user-friendly description early
        if quality_selector == 'audio': choice_description = "Audio Only"
        elif quality_selector == 'gif': choice_description = "GIF (Full Video)"
        elif quality_selector == 'best': choice_description = "Best Quality Video"
        elif quality_selector.startswith('h') and quality_selector[1:].isdigit(): choice_description = f"{quality_selector[1:]}p Video"
        else: choice_description = "Selected Quality"

        try:
            # 1. Download media (pass progress hook directly)
            if status_callback: status_callback(f"🚀 Starting download ({choice_description})... 0%")
            downloaded_path, video_title = await download_media(
                url, quality_selector, progress_hook=progress_callback # Pass hook here
            )
            final_media_path = downloaded_path # Assume this is final unless converting

             # 2. Convert to GIF if requested
            if quality_selector == 'gif':
                if status_callback: status_callback("⏳ Converting to GIF...")
                try:
                    final_media_path = await convert_to_gif(downloaded_path)
                    logger.info(f"GIF conversion successful: {final_media_path}")
                    cleanup_file(downloaded_path) # Clean original video
                    downloaded_path = None # Avoid double cleanup
                except (ConversionError, FileNotFoundError) as conv_e:
                    logger.error(f"GIF conversion failed: {conv_e}")
                    # Don't raise ServiceError here if dl succeeded but conv failed
                    # Handler needs to report this specific error
                    raise # Re-raise ConversionError or FileNotFoundError
                except Exception as e:
                    logger.exception("Unexpected error during GIF conversion")
                    raise ConversionError(f"Unexpected GIF conversion error: {type(e).__name__}") from e

            # 3. Final checks and return
            if not final_media_path or not os.path.exists(final_media_path):
                raise ServiceError("Processed media file not found after download/conversion.")

            logger.info(f"Processing complete for {url}, selector {quality_selector}. Final path: {final_media_path}")
            return final_media_path, video_title, choice_description

        except (DownloaderError, ConversionError, ServiceError) as e:
            # Catch specific errors from download/conversion/service logic
            logger.error(f"Service error during process/download for {url}: {e}")
             # Cleanup intermediate file if download succeeded but conversion failed
            if downloaded_path and downloaded_path != final_media_path:
                 cleanup_file(downloaded_path)
            # Cleanup final path if it exists but error occurred after
            if final_media_path:
                 cleanup_file(final_media_path)
            raise # Re-raise the caught error for the handler
        except Exception as e:
            # Catch unexpected errors
            logger.exception(f"Unexpected service error during process/download for {url}")
            if downloaded_path: cleanup_file(downloaded_path)
            if final_media_path and final_media_path != downloaded_path: cleanup_file(final_media_path)
            raise ServiceError(f"An unexpected error occurred: {type(e).__name__}")
