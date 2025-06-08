# bot/helpers.py
import os
import logging
from typing import Optional
from bot.platforms import get_platform_for_url, is_supported_url

logger = logging.getLogger(__name__)

def is_valid_video_url(url: str) -> bool:
    """Checks if the provided string is a valid video URL from supported platforms."""
    return is_supported_url(url)

def get_platform_name(url: str) -> str:
    """
    Determines the platform name from a URL.
    Returns a user-friendly platform name.
    """
    platform = get_platform_for_url(url)
    return platform.name

def extract_platform_id(url: str) -> Optional[str]:
    """
    Extracts a platform-specific ID from a URL to shorten callback data.
    Returns the ID string or None if not extractable.
    """
    platform = get_platform_for_url(url)
    if platform.supports_id_extraction():
        return platform.extract_id(url)
    return None

def reconstruct_url_from_id(platform_id: str, platform_name: str) -> str:
    """
    Reconstructs a clean URL from platform ID and platform name.
    """
    # Find the platform by name
    from bot.platforms import PLATFORMS

    for platform in PLATFORMS:
        if platform.name.lower().replace('/', '_').replace(' ', '_') == platform_name.lower():
            return platform.reconstruct_url(platform_id)

    # Fallback to returning as-is
    return platform_id

def extract_youtube_video_id(url: str) -> Optional[str]:
    """
    Legacy function - now delegates to YouTube platform.
    Extracts the YouTube video ID from various URL formats.
    """
    from bot.platforms.youtube import YouTubePlatform
    youtube = YouTubePlatform()
    if youtube.matches_url(url):
        return youtube.extract_id(url)
    return None

def extract_tiktok_video_info(url: str) -> Optional[dict]:
    """
    Legacy function - now delegates to TikTok platform.
    Extracts TikTok video information for URL reconstruction.
    """
    from bot.platforms.tiktok import TikTokPlatform
    tiktok = TikTokPlatform()
    if tiktok.matches_url(url):
        return tiktok.extract_video_info(url)
    return None

def extract_twitter_tweet_id(url: str) -> Optional[str]:
    """
    Legacy function - now delegates to Twitter platform.
    Extracts the Twitter/X tweet ID from various URL formats.
    """
    from bot.platforms.twitter import TwitterPlatform
    twitter = TwitterPlatform()
    if twitter.matches_url(url):
        return twitter.extract_id(url)
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
