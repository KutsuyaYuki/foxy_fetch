from typing import List, Dict, Any, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Keep format_filesize if needed elsewhere, otherwise optional
def format_filesize(size_bytes: Optional[int]) -> str:
    if not size_bytes: return ""
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024: return f"{size_bytes / (1024 * 1024):.1f} MB"
    else: return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def create_quality_options_keyboard(
    video_url: str,
    quality_options: List[Dict[str, Any]], # Expects list like [{'height': 720, 'selector': 'h720'}, ...]
    best_quality_option: Dict[str, Any] # Expects dict like {'height': 1080, 'selector': 'best'}
    ) -> InlineKeyboardMarkup:
    """Creates the inline keyboard with dynamic quality options (WITHOUT sizes)."""
    keyboard: List[List[InlineKeyboardButton]] = []

    # Add "Best Available" option first
    best_label = f"🏆 Best ({best_quality_option.get('height', '?')}p)"
    keyboard.append([
        InlineKeyboardButton(
            best_label,
            callback_data=f"q_{best_quality_option.get('selector', 'best')}:{video_url}"
        )
    ])

    # Add other available resolution options
    processed_heights = {best_quality_option.get('height')} # Track added heights
    for option in quality_options:
        height = option.get('height')
        if not height or height in processed_heights:
            continue
        label = f"🎬 {height}p" # Label is just the resolution
        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"q_{option.get('selector', f'h{height}')}:{video_url}"
            )
        ])
        processed_heights.add(height)

    # Add Audio Only option
    keyboard.append([
        InlineKeyboardButton("🎵 Audio Only (m4a)", callback_data=f"q_audio:{video_url}")
    ])

    # Add GIF option
    keyboard.append([
        InlineKeyboardButton("✨ Create GIF (Full Video)", callback_data=f"q_gif:{video_url}")
    ])

    return InlineKeyboardMarkup(keyboard)

# --- Stats Keyboards ---

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
        # Submenu specific buttons will be added by the calling function
        [InlineKeyboardButton("« Back to Main Menu", callback_data="stats_menu:main")]
    ]
    # Based on 'current_menu', add options
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

    # Add more specific buttons here based on the menu context
    # e.g., if current_menu == 'users':
    #   keyboard.insert(0, [InlineKeyboardButton("Show User Count", callback_data="stats_show:user_count")])

    return InlineKeyboardMarkup(keyboard)
