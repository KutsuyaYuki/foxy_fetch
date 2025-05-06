import logging
from functools import wraps
from typing import Callable, Any, Coroutine

from telegram import Update
from telegram.ext import ContextTypes

# Import the set of admin IDs
from bot.config import ADMIN_IDS

logger = logging.getLogger(__name__)

AdminCommandHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, Any]]

def admin_required(func: AdminCommandHandler) -> AdminCommandHandler:
    """
    Decorator to restrict access to a command handler to ADMIN_IDS defined in config.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any) -> None:
        user = update.effective_user
        if not user:
            logger.warning("Admin check failed: effective_user is None.")
            return

        # Check if the user's ID is in the set of admin IDs
        if user.id not in ADMIN_IDS:
            logger.warning(f"Access denied for user {user.id} ({user.username}) to admin command {func.__name__}.")
            # Optional: Reply with access denied message
            # if update.message:
            #     await update.message.reply_text("⛔ Access denied.")
            return

        logger.info(f"Admin access granted for user {user.id} to command {func.__name__}")
        await func(update, context, *args, **kwargs)

    return wrapped
