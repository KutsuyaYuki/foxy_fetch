import asyncio
import logging
import time # Import time for progress throttling
# --- Import Dict from typing ---
from typing import Optional, TYPE_CHECKING, Callable, Dict, Any
# -----------------------------

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

logger = logging.getLogger(__name__)

async def _edit_message_safe(
    bot: Bot, chat_id: int, message_id: int, text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = ParseMode.MARKDOWN
) -> None:
    """Safely edits message text or caption, handling errors."""
    try:
        # Attempt to edit text first
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id,
            reply_markup=reply_markup, parse_mode=parse_mode
        )
    except BadRequest as e:
        if "message has no text" in str(e).lower() or "there is no text" in str(e).lower():
            # If no text, try editing caption
            try:
                await bot.edit_message_caption(
                    caption=text, chat_id=chat_id, message_id=message_id,
                    reply_markup=reply_markup, parse_mode=parse_mode
                )
            except BadRequest as cap_e:
                if "message is not modified" not in str(cap_e).lower():
                    logger.error(f"BadRequest editing caption (fallback): {cap_e}")
        elif "message is not modified" not in str(e).lower():
            logger.debug("Text/Caption not modified.") # Ignore benign error
        elif "can't parse entities" in str(e).lower() and parse_mode is not None:
            logger.warning(f"Parse entity error editing. Retrying without formatting: {e}")
            await _edit_message_safe(bot, chat_id, message_id, text, reply_markup, parse_mode=None) # Retry
        else:
            logger.error(f"BadRequest editing message text: {e}")
    except TelegramError as e:
        if "message to edit not found" in str(e).lower():
            logger.error(f"Message {message_id} not found for editing.")
        else:
            logger.error(f"TelegramError editing message: {e}")
    except Exception as e:
        logger.error(f"Unexpected error editing message: {e}", exc_info=True)


class StatusUpdater:
    """Handles throttled status updates for a Telegram message."""
    def __init__(self, bot: Bot, chat_id: int, message_id: int, loop: 'AbstractEventLoop'):
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.loop = loop
        self.last_update_time = 0.0
        self.last_percentage = -1
        self.throttle_interval_seconds = 1.5
        self.percentage_throttle = 5 # Update every 5% change

    def _schedule_edit(self, text: str, parse_mode: Optional[str] = None) -> None:
        """Schedules the message edit on the event loop."""
        edit_coro = _edit_message_safe(
            self.bot, self.chat_id, self.message_id, text, parse_mode=parse_mode
        )
        asyncio.run_coroutine_threadsafe(edit_coro, self.loop)

    # --- Ensure Dict is imported for this type hint ---
    def update_progress(self, data: Dict[str, Any]) -> None:
    # ---------------------------------------------
        """Processes yt-dlp progress hook data and schedules throttled updates."""
        current_time = time.time()
        if data['status'] == 'downloading':
            try:
                total_bytes_est = data.get('total_bytes_estimate') or data.get('total_bytes')
                if total_bytes_est is None or total_bytes_est == 0: return
                downloaded_bytes = data.get('downloaded_bytes', 0)
                percentage = int((downloaded_bytes / total_bytes_est) * 100)
                # Clamp percentage
                percentage = max(0, min(100, percentage))

                speed = data.get('speed')
                eta = data.get('eta')

                time_since_last = current_time - self.last_update_time
                percentage_diff = abs(percentage - self.last_percentage)

                should_update = (
                    self.last_percentage == -1 or
                    (time_since_last > self.throttle_interval_seconds and percentage_diff >= self.percentage_throttle) or
                    (percentage == 100 and self.last_percentage != 100) # Always update on 100% if not already shown
                )

                if should_update:
                    progress_str = f"🚀 Downloading... {percentage}%"
                    if speed: progress_str += f" ({data.get('_speed_str', '?')})"
                    if eta: progress_str += f" (ETA: {data.get('_eta_str', '?')})"
                    self._schedule_edit(progress_str, parse_mode=None) # Disable parsing for hook data
                    self.last_update_time = current_time
                    self.last_percentage = percentage
            except ZeroDivisionError: logger.warning("Total bytes zero in progress hook.")
            except Exception as e: logger.error(f"Error processing progress hook: {e}", exc_info=True)

        elif data['status'] == 'finished':
            if self.last_percentage != 100:
                 # Ensure 100% is shown
                 self._schedule_edit("🚀 Downloading... 100%", parse_mode=None)
                 self.last_percentage = 100 # Mark 100% as shown

    def update_status(self, text: str, parse_mode: Optional[str] = ParseMode.MARKDOWN) -> None:
        """Directly schedules an edit for non-progress status messages."""
        self._schedule_edit(text, parse_mode=parse_mode)
