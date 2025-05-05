from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def create_download_options_keyboard(video_url: str) -> InlineKeyboardMarkup:
    """Creates the inline keyboard with download options."""
    keyboard = [
        [
            InlineKeyboardButton("🎬 Video + Audio", callback_data=f"download_video_audio:{video_url}")
        ],
        [
            InlineKeyboardButton("🔇 Video Only", callback_data=f"download_video_only:{video_url}")
        ],
        [
            InlineKeyboardButton("🎵 Audio Only (m4a)", callback_data=f"download_audio_only:{video_url}")
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
