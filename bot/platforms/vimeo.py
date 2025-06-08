import re
from .base import BasePlatform

class VimeoPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Vimeo"

    @property
    def domains(self) -> list[str]:
        return ["vimeo.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?vimeo\.com/.+$",
            url, re.IGNORECASE
        ))
