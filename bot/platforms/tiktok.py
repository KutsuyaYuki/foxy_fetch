import re
from typing import Optional, Dict
from .base import BasePlatform

class TikTokPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "TikTok"

    @property
    def domains(self) -> list[str]:
        return ["tiktok.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?tiktok\.com/.+$",
            url, re.IGNORECASE
        ))

    def extract_video_info(self, url: str) -> Optional[Dict[str, str]]:
        """Extracts TikTok video information for URL reconstruction."""
        pattern = r"(?:https?:\/\/)?(?:www\.)?tiktok\.com\/@([\w.-]+)\/video\/(\d+)"
        match = re.search(pattern, url)
        if match:
            return {
                'username': match.group(1),
                'video_id': match.group(2)
            }
        return None

    def extract_id(self, url: str) -> Optional[str]:
        """For TikTok, we don't extract ID due to URL complexity."""
        return None

    def supports_id_extraction(self) -> bool:
        return False
