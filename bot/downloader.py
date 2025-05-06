import asyncio
import logging
import os
import time
import shutil # For checking ffmpeg path
# Add List for type hint
from typing import Dict, Optional, Tuple, Any, Callable, TYPE_CHECKING, List

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

import yt_dlp

from .config import DOWNLOAD_DIR # Import DOWNLOAD_DIR
from .utils import cleanup_file

logger = logging.getLogger(__name__)

logging.getLogger("yt_dlp").setLevel(logging.WARNING)

FFMPEG_PATH = shutil.which("ffmpeg") # Find ffmpeg path

class DownloaderError(Exception):
    """Custom exception for downloader errors."""
    pass

class ConversionError(Exception):
    """Custom exception for GIF conversion errors."""
    pass

# --- GIF Conversion Parameters ---
GIF_FPS = 12
GIF_WIDTH = 480
# --------------------------------

async def run_ffmpeg_command(command: List[str]) -> None:
    """Runs an ffmpeg command using asyncio.create_subprocess_exec."""
    logger.info(f"Running ffmpeg command: {' '.join(command)}")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_message = stderr.decode('utf-8', errors='ignore').strip()
        logger.error(f"ffmpeg command failed with code {process.returncode}:\n{error_message}")
        raise ConversionError(f"ffmpeg failed: {error_message[:200]}") # Limit error length
    else:
        # Log stderr as it often contains useful conversion info even on success
        stderr_output = stderr.decode('utf-8', errors='ignore').strip()
        if stderr_output:
             logger.info(f"ffmpeg stderr output:\n{stderr_output}")
        logger.info("ffmpeg command executed successfully.")


async def convert_to_gif(video_path: str) -> str:
    """Converts the input video file to an optimized GIF using ffmpeg."""
    if not FFMPEG_PATH:
        logger.error("ffmpeg command not found in PATH. Cannot convert to GIF.")
        raise ConversionError("ffmpeg is not installed or not found in PATH.")

    if not os.path.exists(video_path):
        logger.error(f"Input video file not found for GIF conversion: {video_path}")
        raise FileNotFoundError(f"Video file not found: {video_path}")

    base_path = os.path.splitext(video_path)[0]
    palette_path = f"{base_path}_palette.png"
    gif_path = f"{base_path}.gif"

    # ensure output directory exists (should already from downloader)
    os.makedirs(os.path.dirname(gif_path), exist_ok=True)

    try:
        # Pass 1: Generate Palette
        palette_command = [
            FFMPEG_PATH,
            '-i', video_path,
            '-vf', f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,palettegen",
            '-y', # Overwrite palette if exists
            palette_path
        ]
        await run_ffmpeg_command(palette_command)

        # Pass 2: Create GIF using Palette
        gif_command = [
            FFMPEG_PATH,
            '-i', video_path,
            '-i', palette_path,
            '-lavfi', f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos[x];[x][1:v]paletteuse",
            '-y', # Overwrite gif if exists
            gif_path
        ]
        await run_ffmpeg_command(gif_command)

        if not os.path.exists(gif_path):
             raise ConversionError("GIF file was not created after ffmpeg finished.")

        logger.info(f"Successfully created GIF: {gif_path}")
        return gif_path

    except Exception as e:
        # Catch errors from run_ffmpeg_command or other issues
        logger.error(f"Error during GIF conversion process: {e}", exc_info=True)
        # Attempt cleanup of gif path if conversion failed mid-way
        cleanup_file(gif_path)
        # Re-raise as ConversionError for specific handling later
        if isinstance(e, ConversionError):
             raise
        else:
             raise ConversionError(f"Unexpected error during GIF conversion: {type(e).__name__}") from e
    finally:
        # Always clean up the temporary palette file
        cleanup_file(palette_path)


async def get_video_info(url: str) -> Dict:
    # (No change from previous version)
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
        raise DownloaderError(f"Could not get video info. Is the URL correct?\nError: {e.args[0]}")
    except Exception as e:
        logger.error(f"Unexpected error fetching info for {url}: {e}", exc_info=True)
        raise DownloaderError("An unexpected error occurred while fetching video info.")


async def download_media(
    url: str,
    quality_selector: str, # e.g., 'best', 'h720', 'audio', 'gif'
    update_callback: Callable[[str, 'AbstractEventLoop'], None],
    loop: 'AbstractEventLoop'
) -> Tuple[str, str]:
    """Downloads media based on quality selector. For 'gif', downloads low-res video."""
    output_template = os.path.join(DOWNLOAD_DIR, '%(title)s [%(id)s].%(ext)s')

    # --- Progress Hook (no change) ---
    last_update_time = 0.0
    last_percentage = -1
    throttle_interval_seconds = 1.5
    percentage_throttle = 5
    def progress_hook(d: Dict[str, Any]) -> None:
        nonlocal last_update_time, last_percentage
        current_time = time.time()
        # (Keep existing hook logic)
        if d['status'] == 'downloading':
            try:
                total_bytes_est = d.get('total_bytes_estimate') or d.get('total_bytes')
                if total_bytes_est is None or total_bytes_est == 0: return
                downloaded_bytes = d.get('downloaded_bytes', 0)
                percentage = int((downloaded_bytes / total_bytes_est) * 100)
                speed = d.get('speed')
                eta = d.get('eta')
                time_since_last = current_time - last_update_time
                percentage_diff = abs(percentage - last_percentage)
                should_update = (last_percentage == -1 or (time_since_last > throttle_interval_seconds and percentage_diff >= percentage_throttle) or percentage == 100)
                if should_update:
                    progress_str = f"🚀 Downloading... {percentage}%"
                    if speed: progress_str += f" ({d.get('_speed_str', '?')})"
                    if eta: progress_str += f" (ETA: {d.get('_eta_str', '?')})"
                    try: update_callback(progress_str, loop)
                    except Exception as cb_e: logger.error(f"Error executing update_callback: {cb_e}", exc_info=True)
                    last_update_time = current_time
                    last_percentage = percentage
            except ZeroDivisionError: logger.warning("Total bytes estimate is zero")
            except Exception as e: logger.error(f"Error in progress hook calc: {e}", exc_info=True)
        elif d['status'] == 'finished':
            if last_percentage != 100:
                try: update_callback("🚀 Downloading... 100%", loop)
                except Exception as cb_e: logger.error(f"Error executing update_callback for 100%: {cb_e}", exc_info=True)
            logger.info(f"Download hook finished for {d.get('filename', url)}")
        elif d['status'] == 'error': logger.error(f"yt-dlp reported error during download hook for {d.get('filename', url)}")
    # --- End Progress Hook ---


    ydl_opts = {
        'outtmpl': output_template,
        'quiet': False, 'noplaylist': True,
        'progress_hooks': [progress_hook], 'noprogress': True,
        'merge_output_format': 'mp4', # Keep default merge format
    }

    is_merging_needed = False
    format_string = None

    if quality_selector == 'audio':
        logger.info(f"Selecting audio-only format for {url}")
        format_string = 'bestaudio[ext=m4a]/bestaudio'
        ydl_opts['extract_audio'] = True
        ydl_opts['audio_format'] = 'm4a'
        is_merging_needed = True # Post-processing
    # --- Handle GIF: Download low-res video ---
    elif quality_selector == 'gif':
        logger.info(f"Selecting low-res video format for GIF conversion for {url}")
        # Download something like 480p or 360p, video only might be enough if audio not needed for palette
        # Let's prefer mp4 if available for ffmpeg compatibility
        format_string = f'bestvideo[height<=480][ext=mp4]/bestvideo[height<=480]/best[height<=480]'
        # Merging might not strictly be needed if video-only is downloaded first
        # but setting True is safer if fallback occurs. Let ffmpeg handle it.
        is_merging_needed = False # Set to False if video-only is preferred
        ydl_opts['merge_output_format'] = 'mp4' # Ensure output is mp4 for ffmpeg
    # -----------------------------------------
    elif quality_selector == 'best':
        logger.info(f"Selecting best video+audio format for {url}")
        format_string = 'bestvideo+bestaudio/best'
        is_merging_needed = True
    elif quality_selector.startswith('h') and quality_selector[1:].isdigit():
        height = int(quality_selector[1:])
        logger.info(f"Selecting max {height}p video+audio format for {url}")
        format_string = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'
        is_merging_needed = True
    else:
        raise ValueError(f"Invalid quality selector: {quality_selector}")

    ydl_opts['format'] = format_string

    downloaded_file_path: Optional[str] = None
    final_file_path: Optional[str] = None
    info_dict: Optional[Dict] = None

    try:
        logger.info(f"Starting download process for {url} with quality selector '{quality_selector}' (format: '{format_string}')")
        def download_sync():
            nonlocal downloaded_file_path, final_file_path, info_dict
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=True)
                    # Determine final path (more careful)
                    if info_dict and 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                         final_file_path = info_dict['requested_downloads'][0]['filepath']
                         if not os.path.exists(final_file_path) and info_dict.get('filepath'):
                              # Fallback if requested_downloads is wrong but filepath exists (older yt-dlp?)
                              final_file_path = info_dict.get('filepath')
                    elif info_dict and info_dict.get('_filename'): # yt-dlp>=2023.07.06 uses _filename
                         final_file_path = info_dict['_filename']
                    elif info_dict: # Less reliable fallback
                         base, _ = os.path.splitext(ydl.prepare_filename(info_dict))
                         guessed_ext = 'm4a' if quality_selector == 'audio' else 'mp4'
                         final_file_path = f"{base}.{guessed_ext}"
                    else: raise DownloaderError("yt-dlp finished, but info_dict is missing.")

                    if not final_file_path or not os.path.exists(final_file_path):
                         # Try finding the file if determination failed
                         guessed_path = ydl.prepare_filename(info_dict) if info_dict else None
                         if guessed_path and os.path.exists(guessed_path):
                              final_file_path = guessed_path
                              logger.warning(f"Final path determination failed, using found prepared filename: {final_file_path}")
                         elif info_dict:
                              # Check common extensions based on output template
                              base_tmpl, _ = os.path.splitext(output_template)
                              base_name = ydl.prepare_filename(info_dict, outtmpl={'default': base_tmpl})
                              possible_exts = ['mp4', 'mkv', 'webm', 'm4a', 'opus']
                              found_path = None
                              for ext in possible_exts:
                                   test_path = f"{base_name}.{ext}"
                                   if os.path.exists(test_path):
                                        found_path = test_path
                                        break
                              if found_path:
                                   final_file_path = found_path
                                   logger.warning(f"Final path determination failed, found existing file: {final_file_path}")
                              else:
                                   raise DownloaderError(f"Could not determine or find final file path. Base name tried: {base_name}")
                         else:
                               raise DownloaderError("Could not determine final file path.")

                    logger.info(f"yt-dlp extract_info download stage finished. Final path: {final_file_path}")

            except yt_dlp.utils.DownloadError as ydl_err:
                raise DownloaderError(f"Download failed: {ydl_err.args[0]}") from ydl_err

        await loop.run_in_executor(None, download_sync)

        # Post-download checks (merging message only if needed)
        if is_merging_needed and final_file_path and os.path.exists(final_file_path):
            logger.info("Post-processing/merging might be ongoing.")
            try: update_callback("⏳ Post-processing/Merging formats...", loop)
            except Exception as cb_e: logger.error(f"Error executing update_callback for merging: {cb_e}")
            await asyncio.sleep(1)

        if final_file_path and os.path.exists(final_file_path) and info_dict:
            file_title = info_dict.get('title', 'downloaded_file')
            logger.info(f"Download successful. Final path: {final_file_path}")
            return final_file_path, file_title
        else:
            raise DownloaderError("Download completed, but final file could not be found or verified.")

    except DownloaderError as e:
        logger.error(f"DownloaderError for {url}: {e}")
        if final_file_path: cleanup_file(final_file_path) # Cleanup any partial/guessed file
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during download for {url}: {e}")
        if final_file_path: cleanup_file(final_file_path)
        raise DownloaderError(f"An unexpected error occurred during download: {type(e).__name__}")
