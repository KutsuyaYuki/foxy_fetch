# bot/helpers.py
import os
import re
import logging
from urllib.parse import urlparse
from typing import Optional

logger = logging.getLogger(__name__)

# Expanded regex to match various video platforms
SUPPORTED_PLATFORMS_REGEX = re.compile(
    r"^(https?://)?(www\.)?"
    r"(youtube\.com|youtu\.?be|"  # YouTube
    r"tiktok\.com|"  # TikTok
    r"twitter\.com|x\.com|"  # Twitter/X
    r"instagram\.com|"  # Instagram
    r"facebook\.com|fb\.watch|"  # Facebook
    r"vimeo\.com|"  # Vimeo
    r"dailymotion\.com|"  # Dailymotion
    r"twitch\.tv|"  # Twitch
    r"reddit\.com|"  # Reddit
    r"streamable\.com|"  # Streamable
    r"imgur\.com)"  # Imgur
    r"/.+$"
)

def is_valid_video_url(url: str) -> bool:
    """Checks if the provided string is a valid video URL from supported platforms."""
    return bool(SUPPORTED_PLATFORMS_REGEX.match(url))

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

def get_platform_name(url: str) -> str:
    """
    Determines the platform name from a URL.
    Returns a user-friendly platform name.
    """
    url_lower = url.lower()

    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'YouTube'
    elif 'tiktok.com' in url_lower:
        return 'TikTok'
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        return 'Twitter/X'
    elif 'instagram.com' in url_lower:
        return 'Instagram'
    elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
        return 'Facebook'
    elif 'vimeo.com' in url_lower:
        return 'Vimeo'
    elif 'dailymotion.com' in url_lower:
        return 'Dailymotion'
    elif 'twitch.tv' in url_lower:
        return 'Twitch'
    elif 'reddit.com' in url_lower:
        return 'Reddit'
    elif 'streamable.com' in url_lower:
        return 'Streamable'
    elif 'imgur.com' in url_lower:
        return 'Imgur'
    else:
        return 'Video Platform'

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
