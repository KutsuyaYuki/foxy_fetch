from .base import BasePlatform

class GenericPlatform(BasePlatform):

    @property
    def name(self) -> str:
        return "Video Platform"

    @property
    def domains(self) -> list[str]:
        return []

    def matches_url(self, url: str) -> bool:
        """Generic platform matches any URL as fallback."""
        return True
