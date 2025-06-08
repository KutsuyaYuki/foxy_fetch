import re
from .base import BasePlatform

class ImgurPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Imgur"

    @property
    def domains(self) -> list[str]:
        return ["imgur.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?imgur\.com/.+$",
            url, re.IGNORECASE
        ))
