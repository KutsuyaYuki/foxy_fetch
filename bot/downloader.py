import asyncio
import logging
import os
import time
from typing import Dict, Optional, Tuple, Any, Callable # Added Callable

import yt_dlp
# Removed telegram imports as they are not directly used for editing now

# REMOVED: from .handlers import _edit_message_or_caption

from .config import DOWNLOAD_DIR
from .utils import cleanup_file

logger = logging.getLogger(__name__)

logging.getLogger("yt_dlp").setLevel(logging.WARNING)

class DownloaderError(Exception):
    """Custom exception for downloader errors."""
    pass


async def get_video_info(url: str) -> Dict:
    """Fetches video information using yt-dlp."""
    # (No changes in this function)
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': False,
    }
    try:
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


async def download_media(
    url: str,
    format_choice: str,
    # Pass a synchronous callback function for updates
    update_callback: Callable[[str], None],
    # Context is no longer needed here for editing purposes
) -> Tuple[str, str]:
    """
    Downloads media based on the chosen format using yt-dlp,
    reporting progress via a callback.
    """
    output_template = os.path.join(DOWNLOAD_DIR, '%(title)s [%(id)s].%(ext)s')

    last_update_time = 0.0
    last_percentage = -1
    throttle_interval_seconds = 1.5
    percentage_throttle = 5

    def progress_hook(d: Dict[str, Any]) -> None:
        nonlocal last_update_time, last_percentage
        current_time = time.time()

        if d['status'] == 'downloading':
            try:
                total_bytes_est = d.get('total_bytes_estimate') or d.get('total_bytes')
                if total_bytes_est is None or total_bytes_est == 0:
                    logger.debug("Total bytes unknown, skipping percentage calculation.")
                    return

                downloaded_bytes = d.get('downloaded_bytes', 0)
                percentage = int((downloaded_bytes / total_bytes_est) * 100)
                speed = d.get('speed')
                eta = d.get('eta')

                time_since_last = current_time - last_update_time
                percentage_diff = abs(percentage - last_percentage)

                should_update = (
                    last_percentage == -1 or
                    (time_since_last > throttle_interval_seconds and percentage_diff >= percentage_throttle) or
                    percentage == 100
                )

                if should_update:
                    progress_str = f"🚀 Downloading... {percentage}%"
                    if speed:
                        progress_str += f" ({d.get('_speed_str', '?')})"
                    if eta:
                        progress_str += f" (ETA: {d.get('_eta_str', '?')})"

                    # --- Call the synchronous update callback ---
                    try:
                         update_callback(progress_str)
                    except Exception as cb_e:
                         # Log errors from the callback but don't crash the download
                         logger.error(f"Error executing update_callback: {cb_e}", exc_info=True)
                    # ---------------------------------------------

                    last_update_time = current_time
                    last_percentage = percentage

            except ZeroDivisionError:
                 logger.warning("Total bytes estimate is zero, cannot calculate progress.")
            except Exception as e:
                logger.error(f"Error in progress hook calculation: {e}", exc_info=True)

        elif d['status'] == 'finished':
            if last_percentage != 100:
                # Ensure 100% is reported
                try:
                     update_callback("🚀 Downloading... 100%")
                except Exception as cb_e:
                     logger.error(f"Error executing update_callback for 100%: {cb_e}", exc_info=True)
            logger.info(f"Download finished according to hook for {d.get('filename', url)}")

        elif d['status'] == 'error':
            logger.error(f"yt-dlp reported an error during download for {d.get('filename', url)}")
            # Error message handling is in the main handler


    ydl_opts = {
        'outtmpl': output_template,
        'quiet': False,
        'noplaylist': True,
        'progress_hooks': [progress_hook],
        'noprogress': True,
    }

    is_merging_needed = False
    if format_choice == 'video_audio':
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'
        is_merging_needed = True
    elif format_choice == 'video_only':
        ydl_opts['format'] = 'bestvideo[ext=mp4]/bestvideo'
    elif format_choice == 'audio_only':
        ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
        ydl_opts['extract_audio'] = True
        ydl_opts['audio_format'] = 'm4a'
        is_merging_needed = True
    else:
        raise ValueError(f"Invalid format choice: {format_choice}")

    downloaded_file_path: Optional[str] = None
    final_file_path: Optional[str] = None
    info_dict: Optional[Dict] = None

    try:
        logger.info(f"Starting download process for {url} with format {format_choice}")
        loop = asyncio.get_running_loop()

        def download_sync():
            nonlocal downloaded_file_path, final_file_path, info_dict
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                # Determine final path (same logic as before)
                if info_dict and 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                     downloaded_file_path = info_dict['requested_downloads'][0]['filepath']
                     final_file_path = downloaded_file_path
                elif info_dict:
                     base, ext = os.path.splitext(ydl.prepare_filename(info_dict))
                     final_file_path = base + '.' + (ydl_opts.get('audio_format') if format_choice == 'audio_only' \
                                                      else ydl_opts.get('merge_output_format','mp4') if format_choice == 'video_audio' \
                                                      else 'mp4')
                     if not os.path.exists(final_file_path):
                         potential_exts = ['mkv', 'webm', 'mp3', 'opus']
                         found = False
                         for p_ext in potential_exts:
                             temp_path = base + '.' + p_ext
                             if os.path.exists(temp_path):
                                 final_file_path = temp_path
                                 found = True
                                 break
                         if not found and os.path.exists(base + ext):
                             final_file_path = base + ext
                         elif not found:
                              logger.warning(f"Could not reliably determine final file path for {url}. Guessed: {final_file_path}")
                              final_file_path = base + '.' + (ydl_opts.get('audio_format') if format_choice == 'audio_only' \
                                                      else ydl_opts.get('merge_output_format','mp4') if format_choice == 'video_audio' \
                                                      else 'mp4')
                else:
                    raise DownloaderError("Could not get file path after download.")
                logger.info(f"yt-dlp extract_info finished for {url}. Tentative path: {final_file_path}")


        await loop.run_in_executor(None, download_sync)

        if is_merging_needed and final_file_path and os.path.exists(final_file_path):
            logger.info(f"Download part finished for {url}. Post-processing/merging might be ongoing.")
            try:
                update_callback("⏳ Post-processing/Merging formats...")
            except Exception as cb_e:
                logger.error(f"Error executing update_callback for merging status: {cb_e}", exc_info=True)
            # Maybe add a small fixed delay here if merging is usually fast?
            # await asyncio.sleep(1)

        if final_file_path and os.path.exists(final_file_path) and info_dict:
            file_title = info_dict.get('title', 'downloaded_file')
            logger.info(f"Download and processing finished successfully for {url}. Final path: {final_file_path}")
            return final_file_path, file_title
        else:
            logger.error(f"Final file path not found or invalid after download process for {url}. Path: {final_file_path}")
            if downloaded_file_path and downloaded_file_path != final_file_path:
                 cleanup_file(downloaded_file_path)
            if final_file_path:
                  cleanup_file(final_file_path)
            raise DownloaderError("Download process completed, but the final file could not be found.")

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError during download process for {url}: {e}")
        if downloaded_file_path: cleanup_file(downloaded_file_path)
        if final_file_path and final_file_path != downloaded_file_path: cleanup_file(final_file_path)
        raise DownloaderError(f"Download failed. Error: {e.args[0]}")
    except Exception as e:
        logger.exception(f"Unexpected error during download process for {url}: {e}")
        if downloaded_file_path: cleanup_file(downloaded_file_path)
        if final_file_path and final_file_path != downloaded_file_path: cleanup_file(final_file_path)
        raise DownloaderError(f"An unexpected error occurred during download: {type(e).__name__}")
