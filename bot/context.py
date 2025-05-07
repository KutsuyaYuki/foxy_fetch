# bot/context.py
from __future__ import annotations # For Python < 3.9, if Application type hint is needed directly

import logging
from typing import Optional, Dict, Any, TYPE_CHECKING

# Import CallbackContext and ExtBot
from telegram.ext import CallbackContext, ExtBot

if TYPE_CHECKING:
    from telegram.ext import Application
    from bot.database import DatabaseManager

logger = logging.getLogger(__name__)

class CustomContext(CallbackContext[ExtBot, Dict, Dict, Dict]): # Inherit from CallbackContext
    """
    Custom application context class.
    Inherits from CallbackContext.
    """
    # bot_data, user_data, chat_data are inherited from CallbackContext and are automatically populated.
    # application is also inherited and populated by PTB.

    # CallbackContext[ExtBotType, UserDataT, ChatDataT, BotDataT]
    # We use ExtBot for the bot type, and Dict for UserDataT, ChatDataT, BotDataT for simplicity.

    def __init__(self, application: Application, chat_id: Optional[int] = None, user_id: Optional[int] = None):
        # Call the parent constructor
        super().__init__(application=application, chat_id=chat_id, user_id=user_id)
        # Custom attributes can be initialized here if needed,
        # but db_manager is better accessed via application.bot_data anyway.

    @property
    def db_manager(self) -> DatabaseManager:
        """Provides access to the DatabaseManager instance stored in application.bot_data."""
        # self.application is available from CallbackContext
        # self.bot_data corresponds to BotDataT, which we've typed as Dict.
        manager = self.bot_data.get('db_manager')

        if manager is None:
            logger.critical("DatabaseManager not found in application.bot_data.")
            raise RuntimeError("DatabaseManager not initialized correctly.")

        # Runtime type check for robustness, especially if `bot_data` could be tampered with.
        # Avoid direct circular import for type checking tools using TYPE_CHECKING.
        if not TYPE_CHECKING:
            from bot.database import DatabaseManager as ActualDatabaseManager
            if not isinstance(manager, ActualDatabaseManager):
                logger.critical(
                    f"Item 'db_manager' in bot_data is not a DatabaseManager instance, but {type(manager)}."
                )
                raise RuntimeError("DatabaseManager in bot_data is of incorrect type.")

        # We can now be reasonably sure `manager` is a DatabaseManager instance.
        # The `type: ignore` might still be needed if the static type checker cannot fully resolve
        # the type of `manager` due to the conditional import or complex type of `bot_data`.
        return manager # type: ignore[return-value]
