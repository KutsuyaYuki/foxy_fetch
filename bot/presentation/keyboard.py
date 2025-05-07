# bot/presentation/keyboard.py
import logging
from typing import List, Dict, Any, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.helpers import extract_youtube_video_id # Import the new helper

logger = logging.getLogger(__name__)

# format_filesize function (unchanged)
def format_filesize(size_bytes: Optional[int]) -> str:
    if not size_bytes: return ""
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024: return f"{size_bytes / (1024 * 1024):.1f} MB"
    else: return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def create_quality_options_keyboard(
    video_url: str,
    quality_options: List[Dict[str, Any]],
    best_quality_option: Dict[str, Any]
    ) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []

    video_id = extract_youtube_video_id(video_url)
    callback_payload: str

    if not video_id:
        logger.warning(
            f"Could not extract video ID from URL: '{video_url}'. "
            f"Using full URL in callback_data, which may exceed 64-byte limit and cause 'Button_data_invalid'."
        )
        callback_payload = video_url
    else:
        callback_payload = f"id:{video_id}"
        # Max callback_data length with ID: "q_selector(max 7):id:VIDEO_ID(11)" = "q_audio:id:VIDEOID1234" = 7 + 3 + 11 = 21 bytes. Well within 64 byte limit.

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
