import re
from typing import Optional
from .base import BasePlatform

class TwitterPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Twitter/X"

    @property
    def domains(self) -> list[str]:
        return ["twitter.com", "x.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?(twitter\.com|x\.com)/.+$",
            url, re.IGNORECASE
        ))

    def extract_id(self, url: str) -> Optional[str]:
        """Extracts Twitter/X tweet ID from various URL formats."""
        patterns = [
            r"(?:https?:\/\/)?(?:www\.)?(?:twitter\.com|x\.com)\/\w+\/status\/(\d+)",
            r"(?:https?:\/\/)?(?:www\.)?(?:twitter\.com|x\.com)\/i\/web\/status\/(\d+)"
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def reconstruct_url(self, tweet_id: str) -> str:
        """Reconstructs Twitter URL from tweet ID."""
        return f"https://twitter.com/i/web/status/{tweet_id}"

    def supports_id_extraction(self) -> bool:
        return True
