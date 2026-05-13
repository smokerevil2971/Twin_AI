import re
from dataclasses import dataclass
from typing import Optional, List, Tuple, Type
from fastapi import Response

@dataclass
class CommandPayload:
    msg: str
    sender_phone: str
    media_url: str = ""
    media_type: str = ""
    base_url: str = ""
    message_id: str = ""
    button_payload: str = ""
    
    # Store the regex match object so commands can extract groups
    match: Optional[re.Match] = None

class BaseCommand:
    """Base class for all owner commands."""
    async def execute(self, payload: CommandPayload) -> Optional[Response]:
        raise NotImplementedError

COMMAND_REGISTRY: List[Tuple[re.Pattern, BaseCommand]] = []

def register_command(pattern: str, exact: bool = False, flags: int = re.IGNORECASE | re.DOTALL):
    """
    Decorator to register a command.
    If exact=True, the pattern must match the entire string exactly.
    """
    def decorator(cls: Type[BaseCommand]):
        regex_pattern = f"^{pattern}$" if exact else pattern
        compiled_pattern = re.compile(regex_pattern, flags)
        COMMAND_REGISTRY.append((compiled_pattern, cls()))
        return cls
    return decorator

# Upload handling is a special case since it triggers on media attachment + MIME type
UPLOAD_HANDLERS: List[BaseCommand] = []

def register_upload_handler():
    """Decorator to register a handler that processes media uploads."""
    def decorator(cls: Type[BaseCommand]):
        UPLOAD_HANDLERS.append(cls())
        return cls
    return decorator
