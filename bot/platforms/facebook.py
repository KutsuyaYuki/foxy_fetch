import re
from .base import BasePlatform

class FacebookPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Facebook"

    @property
    def domains(self) -> list[str]:
        return ["facebook.com", "fb.watch"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?(facebook\.com|fb\.watch)/.+$",
            url, re.IGNORECASE
        ))
