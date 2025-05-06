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
