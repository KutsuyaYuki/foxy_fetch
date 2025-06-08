import re
from .base import BasePlatform

class RedditPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Reddit"

    @property
    def domains(self) -> list[str]:
        return ["reddit.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?reddit\.com/.+$",
            url, re.IGNORECASE
        ))
