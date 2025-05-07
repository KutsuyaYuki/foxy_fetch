# bot/helpers.py
import os
import re
import logging
from urllib.parse import urlparse
from typing import Optional # Added Optional

logger = logging.getLogger(__name__)

YOUTUBE_REGEX = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$"
)

def is_valid_youtube_url(url: str) -> bool:
    """Checks if the provided string is a valid YouTube URL."""
    return bool(YOUTUBE_REGEX.match(url))

def extract_youtube_video_id(url: str) -> Optional[str]:
    """
    Extracts the YouTube video ID from various URL formats.
    Returns the video ID string or None if not found.
    """
    # Patterns to match YouTube video IDs
    # Covers:
    # - youtube.com/watch?v=VIDEO_ID
    # - youtu.be/VIDEO_ID
    # - youtube.com/embed/VIDEO_ID
    # - youtube.com/shorts/VIDEO_ID
    # - youtube.com/live/VIDEO_ID
    # Accounts for variations with www, http/https, and extra parameters.
    patterns = [
        r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:watch\?v=|embed\/|shorts\/|live\/|v\/|attribution_link\?a=.*&u=\/watch\?v%3D)([0-9A-Za-z_-]{11})(?:[?&]|$)",
        r"(?:https?:\/\/)?(?:www\.)?youtu\.be\/([0-9A-Za-z_-]{11})(?:[?&]|$)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1) # Return the first capturing group (the video ID)
    return None

def cleanup_file(file_path: str) -> None:
    """Attempts to delete a file and logs errors."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")
    except OSError as e:
        logger.error(f"Error deleting file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during file cleanup {file_path}: {e}")
