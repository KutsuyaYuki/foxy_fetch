from .base import BasePlatform
from .youtube import YouTubePlatform
from .tiktok import TikTokPlatform
from .twitter import TwitterPlatform
from .instagram import InstagramPlatform
from .facebook import FacebookPlatform
from .vimeo import VimeoPlatform
from .dailymotion import DailymotionPlatform
from .twitch import TwitchPlatform
from .reddit import RedditPlatform
from .streamable import StreamablePlatform
from .imgur import ImgurPlatform
from .generic import GenericPlatform

# Platform registry - order matters for URL matching priority
PLATFORMS = [
    YouTubePlatform(),
    TikTokPlatform(),
    TwitterPlatform(),
    InstagramPlatform(),
    FacebookPlatform(),
    VimeoPlatform(),
    DailymotionPlatform(),
    TwitchPlatform(),
    RedditPlatform(),
    StreamablePlatform(),
    ImgurPlatform(),
    GenericPlatform(),  # Fallback platform should be last
]

def get_platform_for_url(url: str) -> BasePlatform:
    """Returns the appropriate platform handler for the given URL."""
    for platform in PLATFORMS:
        if platform.matches_url(url):
            return platform
    return GenericPlatform()  # Fallback

def is_supported_url(url: str) -> bool:
    """Checks if any platform supports the given URL."""
    for platform in PLATFORMS[:-1]:  # Exclude generic platform
        if platform.matches_url(url):
            return True
    return False

__all__ = [
    'BasePlatform',
    'PLATFORMS',
    'get_platform_for_url',
    'is_supported_url',
]
