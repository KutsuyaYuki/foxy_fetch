import re
from .base import BasePlatform

class TwitchPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Twitch"

    @property
    def domains(self) -> list[str]:
        return ["twitch.tv"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?twitch\.tv/.+$",
            url, re.IGNORECASE
        ))
