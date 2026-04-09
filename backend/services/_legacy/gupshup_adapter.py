"""
Backward-compatibility shim — gupshup_adapter is now messaging_adapter.

This file is kept so any code that still imports from `services.gupshup_adapter`
continues to work without changes. All symbols are re-exported from messaging_adapter.

DO NOT add new code here. Use services.messaging_adapter directly.
"""
from services.messaging_adapter import (  # noqa: F401
    MessagingAdapter as GupshupAdapter,   # old ABC name
    MockMessagingAdapter as MockGupshupAdapter,
    get_messaging_adapter,
    get_messaging_adapter as get_gupshup_adapter,  # legacy alias
)
