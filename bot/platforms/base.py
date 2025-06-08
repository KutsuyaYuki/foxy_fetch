from abc import ABC, abstractmethod
from typing import Optional
import re

class BasePlatform(ABC):
    """Abstract base class for all platform handlers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the display name of the platform."""
        pass

    @property
    @abstractmethod
    def domains(self) -> list[str]:
        """Returns list of domains this platform handles."""
        pass

    @abstractmethod
    def matches_url(self, url: str) -> bool:
        """Returns True if this platform can handle the given URL."""
        pass

    def extract_id(self, url: str) -> Optional[str]:
        """Extracts platform-specific ID from URL. Returns None if not extractable."""
        return None

    def reconstruct_url(self, platform_id: str) -> str:
        """Reconstructs URL from platform ID."""
        return platform_id  # Default: return as-is

    def get_short_name(self) -> str:
        """Returns short name for callback payloads."""
        return self.name.lower().replace('/', '_').replace(' ', '_')

    def supports_id_extraction(self) -> bool:
        """Returns True if this platform supports ID extraction for callback optimization."""
        return False

    def _create_domain_regex(self) -> re.Pattern:
        """Helper to create regex pattern from domains list."""
        escaped_domains = [re.escape(domain) for domain in self.domains]
        pattern = r"^(https?://)?(www\.)?(" + "|".join(escaped_domains) + r")/.+$"
        return re.compile(pattern, re.IGNORECASE)
