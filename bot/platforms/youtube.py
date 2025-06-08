import re
from typing import Optional
from .base import BasePlatform

class YouTubePlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "YouTube"

    @property
    def domains(self) -> list[str]:
        return ["youtube.com", "youtu.be"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$",
            url, re.IGNORECASE
        ))

    def extract_id(self, url: str) -> Optional[str]:
        """Extracts YouTube video ID from various URL formats."""
        patterns = [
            r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:watch\?v=|embed\/|shorts\/|live\/|v\/|attribution_link\?a=.*&u=\/watch\?v%3D)([0-9A-Za-z_-]{11})(?:[?&]|$)",
            r"(?:https?:\/\/)?(?:www\.)?youtu\.be\/([0-9A-Za-z_-]{11})(?:[?&]|$)"
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def reconstruct_url(self, video_id: str) -> str:
        """Reconstructs YouTube URL from video ID."""
        return f"https://www.youtube.com/watch?v={video_id}"

    def supports_id_extraction(self) -> bool:
        return True
