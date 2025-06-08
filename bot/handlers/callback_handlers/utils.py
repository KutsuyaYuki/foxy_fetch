import logging
from typing import Optional, Tuple
from bot.presentation.keyboard import resolve_callback_payload

logger = logging.getLogger(__name__)

def parse_download_callback(data: str) -> Optional[Tuple[str, str]]:
    """Parse download callback data into quality selector and URL."""
    try:
        action_part, payload = data.split(":", 1)
        if not action_part.startswith("q_"):
            logger.warning(f"Callback data '{data}' is not a download action (no 'q_' prefix).")
            return None
        quality_selector = action_part[2:]

        try:
            original_url = resolve_callback_payload(payload)
            logger.debug(f"Resolved payload '{payload}' to URL '{original_url}' for quality '{quality_selector}'")
            return quality_selector, original_url
        except ValueError as e:
            logger.error(f"Failed to resolve callback payload '{payload}': {e}")
            return None

    except ValueError:
        logger.warning(f"Could not split callback data into action and payload: '{data}'")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing download callback data '{data}': {e}", exc_info=True)
        return None

def parse_stats_callback(data: str) -> Optional[Tuple[str, str]]:
    """Parse stats callback data into menu type and action."""
    try:
        prefix, action = data.split(":", 1)
        if prefix not in ("stats_menu", "stats_show"):
            return None
        return prefix, action
    except (ValueError, AttributeError):
        logger.warning(f"Could not parse stats callback data: {data}")
        return None
