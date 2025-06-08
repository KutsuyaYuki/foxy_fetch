import re
from .base import BasePlatform

class DailymotionPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Dailymotion"

    @property
    def domains(self) -> list[str]:
        return ["dailymotion.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?dailymotion\.com/.+$",
            url, re.IGNORECASE
        ))
