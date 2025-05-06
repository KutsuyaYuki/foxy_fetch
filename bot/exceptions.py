# bot/exceptions.py

class DownloaderError(Exception):
    """Custom exception for yt-dlp related errors."""
    pass

class ConversionError(Exception):
    """Custom exception for media conversion (e.g., GIF) errors."""
    pass

class ServiceError(Exception):
    """Custom exception for general service layer errors."""
    pass
