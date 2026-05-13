# Import all command modules so they register themselves
from handlers.owner_commands.base import COMMAND_REGISTRY, UPLOAD_HANDLERS, CommandPayload
from handlers.owner_commands import system_commands
from handlers.owner_commands import broadcast_commands
from handlers.owner_commands import product_offer_commands
from handlers.owner_commands import client_commands
from handlers.owner_commands import analytics_commands
from handlers.owner_commands import upload_commands
from handlers.owner_commands import kb_commands

# Expose them
__all__ = ["COMMAND_REGISTRY", "UPLOAD_HANDLERS", "CommandPayload"]
