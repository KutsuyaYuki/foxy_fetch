import re
from .base import BasePlatform

class InstagramPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Instagram"

    @property
    def domains(self) -> list[str]:
        return ["instagram.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?instagram\.com/.+$",
            url, re.IGNORECASE
        ))
