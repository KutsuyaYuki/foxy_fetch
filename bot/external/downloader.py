import asyncio
import logging
import os
import time
import yt_dlp
from typing import Dict, Optional, Tuple, Any, Callable, TYPE_CHECKING

from bot.config import DOWNLOAD_DIR
# --- Corrected Import: from bot.helpers ---
from bot.helpers import cleanup_file
# -----------------------------------------
# Import exceptions from the new location
from bot.exceptions import DownloaderError

logger = logging.getLogger(__name__)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)


async def get_video_info(url: str) -> Dict:
    """Fetches video information including formats using yt-dlp."""
    ydl_opts = {'quiet': True, 'skip_download': True, 'force_generic_extractor': False}
    try:
        logger.info(f"Fetching video info for {url}")
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        if 'formats' not in info_dict or not info_dict['formats']:
            raise DownloaderError("Could not retrieve video format list.")
        logger.info(f"Successfully fetched info with {len(info_dict.get('formats',[]))} formats for {url}")
        return info_dict
    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e)
        if "video unavailable" in err_msg.lower(): raise DownloaderError("This video is unavailable.")
        elif "private video" in err_msg.lower(): raise DownloaderError("This is a private video.")
        logger.error(f"yt-dlp DownloadError fetching info for {url}: {e}")
        raise DownloaderError(f"Could not get video info: {e.args[0]}")
    except Exception as e:
        logger.error(f"Unexpected error fetching info for {url}: {e}", exc_info=True)
        raise DownloaderError(f"Unexpected error fetching video info: {type(e).__name__}")


async def download_media(
    url: str,
    quality_selector: str, # e.g., 'best', 'h720', 'audio', 'gif'
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None # Progress hook is now optional
) -> Tuple[str, str]:
    """
    Downloads media based on the chosen quality selector using yt-dlp.
    Returns the final file path and video title.
    Handles progress reporting via an optional hook.
    Does NOT perform GIF conversion.
    """
    output_template = os.path.join(DOWNLOAD_DIR, '%(title)s [%(id)s].%(ext)s')

    ydl_opts = {
        'outtmpl': output_template,
        'quiet': False, 'noplaylist': True,
        'progress_hooks': [progress_hook] if progress_hook else [], # Use hook if provided
        'noprogress': True,
        'merge_output_format': 'mp4', # Keep default merge format
    }

    format_string = None
    if quality_selector == 'audio':
        # More flexible audio format selection with multiple fallbacks
        format_string = 'bestaudio/best[acodec!=none]/best'
        ydl_opts['extract_audio'] = True
        ydl_opts['audio_format'] = 'm4a'
        ydl_opts['audio_quality'] = '192'
    elif quality_selector == 'gif':
        # Flexible format selection for GIF conversion - just get the best available
        format_string = 'best'
        ydl_opts['merge_output_format'] = 'mp4'
    elif quality_selector == 'best':
        # Try combined format first, fallback to best single format
        format_string = 'bestvideo+bestaudio/best'
    elif quality_selector.startswith('h') and quality_selector[1:].isdigit():
        height = int(quality_selector[1:])
        # More flexible height-based selection with fallbacks
        format_string = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/bestvideo[height<={height}]/best'
    else:
        raise ValueError(f"Invalid quality selector: {quality_selector}")

    ydl_opts['format'] = format_string
    logger.info(f"Using format string: {format_string}")

    final_file_path: Optional[str] = None
    info_dict: Optional[Dict] = None

    try:
        logger.info(f"Starting yt-dlp download for {url} with selector '{quality_selector}'")
        loop = asyncio.get_running_loop()

        def download_sync():
            nonlocal final_file_path, info_dict
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=True)
                    # Determine final path carefully
                    path_keys = ['filepath', '_filename'] # Check these keys first
                    found_path = None
                    if info_dict:
                         if 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                             found_path = info_dict['requested_downloads'][0].get('filepath')
                         if not found_path:
                              for key in path_keys:
                                   if info_dict.get(key):
                                        found_path = info_dict[key]
                                        break
                         if not found_path: # Fallback to prepare_filename
                              found_path = ydl.prepare_filename(info_dict)

                    if found_path and os.path.exists(found_path):
                         final_file_path = found_path
                    elif found_path: # Path determined but doesn't exist? Try correcting extension.
                         base, _ = os.path.splitext(found_path)
                         # Try different extensions based on quality selector
                         if quality_selector == 'audio':
                             extensions = ['m4a', 'mp3', 'aac', 'ogg', 'wav']
                         else:
                             extensions = ['mp4', 'webm', 'mkv', 'avi', 'mov', 'flv']

                         for ext in extensions:
                             corrected_path = f"{base}.{ext}"
                             if os.path.exists(corrected_path):
                                 final_file_path = corrected_path
                                 break

                         if not final_file_path:
                             raise DownloaderError(f"Determined path '{found_path}' but file not found with any extension.")
                    else: # Should not happen if download succeeded
                        raise DownloaderError("yt-dlp finished, but could not determine file path.")

                    logger.info(f"yt-dlp download sync finished. Final path: {final_file_path}")

            except yt_dlp.utils.DownloadError as ydl_err:
                raise DownloaderError(f"Download failed: {ydl_err.args[0]}") from ydl_err
            except Exception as sync_err: # Catch other sync errors
                logger.exception("Error during synchronous download part")
                raise DownloaderError(f"Sync download error: {sync_err}") from sync_err

        await loop.run_in_executor(None, download_sync)

        if final_file_path and os.path.exists(final_file_path) and info_dict:
            file_title = info_dict.get('title', 'downloaded_file')
            logger.info(f"Download successful: {final_file_path}")
            return final_file_path, file_title
        else:
            # This case handles if run_in_executor finished but path logic failed
            raise DownloaderError("Download process ok, but final file path invalid or missing.")

    except DownloaderError as e: # Catch errors raised within download_sync or path logic
        logger.error(f"DownloaderError for {url}: {e}")
        if final_file_path: cleanup_file(final_file_path) # Cleanup any partial/guessed file
        raise # Re-raise the specific DownloaderError
    except Exception as e: # Catch unexpected errors (e.g., loop errors)
        logger.exception(f"Unexpected error during download media call for {url}: {e}")
        if final_file_path: cleanup_file(final_file_path)
        raise DownloaderError(f"Unexpected download error: {type(e).__name__}") from e
