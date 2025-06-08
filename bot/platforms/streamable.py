import re
from .base import BasePlatform

class StreamablePlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Streamable"

    @property
    def domains(self) -> list[str]:
        return ["streamable.com"]

    def matches_url(self, url: str) -> bool:
        return bool(re.match(
            r"^(https?://)?(www\.)?streamable\.com/.+$",
            url, re.IGNORECASE
        ))
