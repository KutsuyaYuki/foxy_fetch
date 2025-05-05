import os
import re
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

YOUTUBE_REGEX = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$"
)

def is_valid_youtube_url(url: str) -> bool:
    """Checks if the provided string is a valid YouTube URL."""
    return bool(YOUTUBE_REGEX.match(url))

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
