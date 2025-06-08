# bot/presentation/keyboard.py
import logging
import hashlib
from typing import List, Dict, Any, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.helpers import extract_platform_id, get_platform_name

logger = logging.getLogger(__name__)

# format_filesize function (unchanged)
def format_filesize(size_bytes: Optional[int]) -> str:
    if not size_bytes: return ""
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024: return f"{size_bytes / (1024 * 1024):.1f} MB"
    else: return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def create_callback_payload(video_url: str) -> str:
    """
    Creates an optimized callback payload that fits within Telegram's 64-byte limit.
    Uses platform-specific ID extraction or URL hashing as fallback.
    """
    platform_name = get_platform_name(video_url)

    # Only try to shorten URLs for platforms we can reliably reconstruct
    if platform_name in ['YouTube', 'Twitter/X']:
        platform_id = extract_platform_id(video_url)
        if platform_id:
            platform_short = platform_name.lower().replace('/', '_').replace(' ', '_')
            payload = f"{platform_short}:{platform_id}"

            # Check if it fits within reasonable limit
            if len(payload) <= 45:  # Max 64 - "q_best:" (7 chars) - buffer
                logger.debug(f"Using platform ID payload for {platform_name}: {payload}")
                return payload

    # For TikTok and other platforms, always use hash method
    url_hash = hashlib.md5(video_url.encode()).hexdigest()[:12]
    payload = f"hash:{url_hash}"
    logger.debug(f"Using hash payload for {platform_name} URL: {payload}")

    # Store the full URL mapping
    _url_cache[url_hash] = video_url

    return payload

# Simple in-memory cache for URL hashes (in production, use Redis or database)
_url_cache: Dict[str, str] = {}

def resolve_callback_payload(payload: str) -> str:
    """
    Resolves a callback payload back to the original URL.
    """
    if payload.startswith("hash:"):
        hash_key = payload[5:]
        if hash_key in _url_cache:
            original_url = _url_cache[hash_key]
            logger.debug(f"Resolved hash {hash_key} to URL: {original_url}")
            return original_url
        else:
            logger.error(f"Hash key {hash_key} not found in URL cache")
            raise ValueError(f"Could not resolve URL from hash: {hash_key}")

    # Handle platform-specific IDs
    if ":" in payload:
        platform, platform_id = payload.split(":", 1)

        if platform == "youtube":
            return f"https://www.youtube.com/watch?v={platform_id}"
        elif platform in ["twitter_x", "twitter"]:
            return f"https://twitter.com/i/web/status/{platform_id}"
        else:
            logger.warning(f"Unknown platform in payload: {platform}")
            raise ValueError(f"Unknown platform in callback payload: {platform}")

    # If no special format, this shouldn't happen
    logger.error(f"Unrecognized callback payload format: {payload}")
    raise ValueError(f"Invalid callback payload format: {payload}")

def create_quality_options_keyboard(
    video_url: str,
    quality_options: List[Dict[str, Any]],
    best_quality_option: Dict[str, Any]
    ) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []

    try:
        callback_payload = create_callback_payload(video_url)
    except Exception as e:
        logger.error(f"Error creating callback payload for {video_url}: {e}")
        # Fallback to a very short hash
        fallback_hash = hashlib.md5(video_url.encode()).hexdigest()[:8]
        callback_payload = f"hash:{fallback_hash}"
        _url_cache[fallback_hash] = video_url

    # Add "Best Available" option first
    best_label = f"🏆 Best ({best_quality_option.get('height', '?')}p)"
    keyboard.append([
        InlineKeyboardButton(
            best_label,
            callback_data=f"q_{best_quality_option.get('selector', 'best')}:{callback_payload}"
        )
    ])

    # Add other available resolution options
    processed_heights = {best_quality_option.get('height')}
    for option in quality_options:
        height = option.get('height')
        if not height or height in processed_heights:
            continue
        label = f"🎬 {height}p"
        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"q_{option.get('selector', f'h{height}')}:{callback_payload}"
            )
        ])
        processed_heights.add(height)

    # Add Audio Only option
    keyboard.append([
        InlineKeyboardButton("🎵 Audio Only (m4a)", callback_data=f"q_audio:{callback_payload}")
    ])

    # Add GIF option
    keyboard.append([
        InlineKeyboardButton("✨ Create GIF (Full Video)", callback_data=f"q_gif:{callback_payload}")
    ])

    return InlineKeyboardMarkup(keyboard)

# --- Stats Keyboards (unchanged) ---

def create_stats_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Creates the main menu keyboard for the /stats command."""
    keyboard = [
        [
            InlineKeyboardButton("👤 User Statistics", callback_data="stats_menu:users"),
            InlineKeyboardButton("💬 Interaction Stats", callback_data="stats_menu:interactions"),
        ],
        [
            InlineKeyboardButton("📥 Download Statistics", callback_data="stats_menu:downloads"),
            InlineKeyboardButton("📊 Overall Summary", callback_data="stats_show:summary"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def create_stats_submenu_keyboard(current_menu: str) -> InlineKeyboardMarkup:
    """Creates a submenu keyboard with a back button."""
    keyboard = [
        [InlineKeyboardButton("« Back to Main Menu", callback_data="stats_menu:main")]
    ]
    if current_menu == "users":
         keyboard.insert(0, [InlineKeyboardButton("Total Users", callback_data="stats_show:users_total")])
         keyboard.insert(1, [InlineKeyboardButton("Active Users (24h)", callback_data="stats_show:users_active_24h")])
         keyboard.insert(2, [InlineKeyboardButton("Active Users (7d)", callback_data="stats_show:users_active_7d")])
    elif current_menu == "interactions":
         keyboard.insert(0, [InlineKeyboardButton("Total by Type", callback_data="stats_show:interactions_by_type")])
         keyboard.insert(1, [InlineKeyboardButton("Interactions (24h)", callback_data="stats_show:interactions_24h")])
    elif current_menu == "downloads":
         keyboard.insert(0, [InlineKeyboardButton("Count by Status", callback_data="stats_show:downloads_by_status")])
         keyboard.insert(1, [InlineKeyboardButton("Completed by Quality", callback_data="stats_show:downloads_by_quality")])
         keyboard.insert(2, [InlineKeyboardButton("Top 5 URLs", callback_data="stats_show:downloads_top_urls")])
    return InlineKeyboardMarkup(keyboard)
