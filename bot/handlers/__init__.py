from .command_handlers import command_handlers
from .message_handlers import message_handlers
from .callback_handlers import callback_handlers

# Combine all handlers into a single list
all_handlers = command_handlers + message_handlers + callback_handlers
