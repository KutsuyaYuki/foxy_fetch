import asyncio
import logging
import os
from typing import Dict, Optional, Tuple
import yt_dlp

from .config import DOWNLOAD_DIR
from .utils import cleanup_file

logger = logging.getLogger(__name__)

# Configure yt-dlp logger to avoid excessive output
logging.getLogger("yt_dlp").setLevel(logging.WARNING)


class DownloaderError(Exception):
    """Custom exception for downloader errors."""
    pass


async def get_video_info(url: str) -> Dict:
    """Fetches video information using yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': False,
    }
    try:
        # Run yt-dlp in a separate thread to avoid blocking asyncio event loop
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        return info_dict
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError fetching info for {url}: {e}")
        raise DownloaderError(f"Could not fetch video info. Is the URL correct? Error: {e.args[0]}")
    except Exception as e:
        logger.error(f"Unexpected error fetching info for {url}: {e}")
        raise DownloaderError(f"An unexpected error occurred while fetching video info: {type(e).__name__}")


async def download_media(url: str, format_choice: str) -> Tuple[str, str]:
    """Downloads media based on the chosen format using yt-dlp."""
    output_template = os.path.join(DOWNLOAD_DIR, '%(title)s [%(id)s].%(ext)s')
    ydl_opts = {
        'outtmpl': output_template,
        'quiet': False, # Set to False to see progress/errors in logs if needed
        'noplaylist': True,
        'progress_hooks': [], # Add hooks here for progress reporting if implemented later
        # Add more options like format selection, postprocessors etc.
    }

    # Choose the best format based on user selection
    if format_choice == 'video_audio':
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4' # Sensible default
    elif format_choice == 'video_only':
        ydl_opts['format'] = 'bestvideo[ext=mp4]/bestvideo' # Prefer mp4 if available
    elif format_choice == 'audio_only':
        ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
        ydl_opts['extract_audio'] = True
        ydl_opts['audio_format'] = 'm4a' # Common and usually compatible
    else:
        raise ValueError(f"Invalid format choice: {format_choice}")

    downloaded_file_path: Optional[str] = None
    final_file_path: Optional[str] = None
    info_dict: Optional[Dict] = None

    try:
        logger.info(f"Starting download for {url} with format {format_choice}")
        loop = asyncio.get_running_loop()

        def download_sync():
            nonlocal downloaded_file_path, final_file_path, info_dict
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                # yt-dlp might change the extension or filename during post-processing
                # 'requested_downloads' usually contains the final file path
                if info_dict and 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                     downloaded_file_path = info_dict['requested_downloads'][0]['filepath']
                     final_file_path = downloaded_file_path # Keep track of the correct final path
                elif info_dict:
                     # Fallback if 'requested_downloads' is not available (might happen for some extractors)
                     # Construct path based on template and extracted info
                     base, ext = os.path.splitext(ydl.prepare_filename(info_dict))
                     final_file_path = base + '.' + (ydl_opts.get('audio_format') if format_choice == 'audio_only' \
                                                      else ydl_opts.get('merge_output_format','mp4') if format_choice == 'video_audio' \
                                                      else 'mp4') # Guess extension based on options
                     if not os.path.exists(final_file_path):
                         # Try common video/audio extensions if the constructed path is wrong
                         potential_exts = ['mkv', 'webm', 'mp3', 'opus']
                         found = False
                         for p_ext in potential_exts:
                             temp_path = base + '.' + p_ext
                             if os.path.exists(temp_path):
                                 final_file_path = temp_path
                                 found = True
                                 break
                         if not found and os.path.exists(base + ext): # Last resort: original ext
                             final_file_path = base + ext
                         elif not found:
                              # If we still can't find it, log an error but proceed, upload might fail later
                              logger.warning(f"Could not reliably determine final file path for {url}. Guessed: {final_file_path}")
                              # Set it back to the best guess to attempt upload
                              final_file_path = base + '.' + (ydl_opts.get('audio_format') if format_choice == 'audio_only' \
                                                      else ydl_opts.get('merge_output_format','mp4') if format_choice == 'video_audio' \
                                                      else 'mp4')

                else:
                    raise DownloaderError("Could not get file path after download.")
                logger.info(f"Download finished for {url}. File path: {final_file_path}")

        await loop.run_in_executor(None, download_sync)

        if final_file_path and os.path.exists(final_file_path) and info_dict:
            file_title = info_dict.get('title', 'downloaded_file')
            return final_file_path, file_title
        else:
             logger.error(f"Final file path not found or invalid after download for {url}. Path: {final_file_path}")
             # Attempt cleanup even if path determination failed partially
             if downloaded_file_path and downloaded_file_path != final_file_path:
                 cleanup_file(downloaded_file_path)
             if final_file_path:
                  cleanup_file(final_file_path) # Cleanup the guessed path too
             raise DownloaderError("Download completed, but the final file could not be found.")

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError during download for {url}: {e}")
        # Attempt cleanup if a partial file path was determined
        if downloaded_file_path: cleanup_file(downloaded_file_path)
        if final_file_path and final_file_path != downloaded_file_path: cleanup_file(final_file_path)
        raise DownloaderError(f"Download failed. Error: {e.args[0]}")
    except Exception as e:
        logger.exception(f"Unexpected error during download process for {url}: {e}")
        # ```python
        # Attempt cleanup if file paths were determined
        if downloaded_file_path: cleanup_file(downloaded_file_path)
        if final_file_path and final_file_path != downloaded_file_path: cleanup_file(final_file_path)
        raise DownloaderError(f"An unexpected error occurred during download: {type(e).__name__}")
