from .download_callbacks import download_callback_handler
from .stats_callbacks import stats_callback_handler

callback_handlers = [download_callback_handler, stats_callback_handler]

__all__ = ['callback_handlers']
