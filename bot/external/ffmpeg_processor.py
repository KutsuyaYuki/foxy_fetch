import asyncio
import logging
import os
import shutil
from typing import List

from bot.exceptions import ConversionError
# --- Corrected Import: from bot.helpers ---
from bot.helpers import cleanup_file
# -----------------------------------------

logger = logging.getLogger(__name__)

# Constants (could be moved to config if needed)
GIF_FPS = 12
GIF_WIDTH = 480
FFMPEG_PATH = shutil.which("ffmpeg")

async def run_ffmpeg_command(command: List[str]) -> None:
    """Runs an ffmpeg command using asyncio.create_subprocess_exec."""
    if not FFMPEG_PATH:
        logger.error("ffmpeg command not found in PATH.")
        raise ConversionError("ffmpeg is not installed or not found in PATH.")

    logger.info(f"Running ffmpeg: {' '.join(command)}")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_message = stderr.decode('utf-8', errors='ignore').strip()
        logger.error(f"ffmpeg failed (code {process.returncode}):\n{error_message}")
        raise ConversionError(f"ffmpeg failed: {error_message[:200]}")
    else:
        stderr_output = stderr.decode('utf-8', errors='ignore').strip()
        if stderr_output: logger.debug(f"ffmpeg stderr:\n{stderr_output}") # Debug log
        logger.info("ffmpeg command successful.")

async def convert_to_gif(video_path: str) -> str:
    """Converts the input video file to an optimized GIF using ffmpeg."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video not found: {video_path}")

    base_path = os.path.splitext(video_path)[0]
    palette_path = f"{base_path}_palette.png"
    gif_path = f"{base_path}.gif"
    os.makedirs(os.path.dirname(gif_path), exist_ok=True)

    try:
        # Pass 1: Generate Palette
        palette_command = [
            FFMPEG_PATH, '-i', video_path,
            '-vf', f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,palettegen",
            '-y', palette_path
        ]
        await run_ffmpeg_command(palette_command)

        # Pass 2: Create GIF using Palette
        gif_command = [
            FFMPEG_PATH, '-i', video_path, '-i', palette_path,
            '-lavfi', f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos[x];[x][1:v]paletteuse",
            '-y', gif_path
        ]
        await run_ffmpeg_command(gif_command)

        if not os.path.exists(gif_path):
             raise ConversionError("GIF file not created after ffmpeg finished.")

        logger.info(f"Successfully created GIF: {gif_path}")
        return gif_path

    except Exception as e:
        logger.error(f"Error during GIF conversion: {e}", exc_info=True)
        cleanup_file(gif_path) # Attempt cleanup
        if isinstance(e, ConversionError): raise
        else: raise ConversionError(f"Unexpected GIF conversion error: {type(e).__name__}") from e
    finally:
        cleanup_file(palette_path) # Always cleanup palette
