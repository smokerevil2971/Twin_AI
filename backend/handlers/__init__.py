from handlers.event import InboundEvent
from handlers.delivery import DeliveryHandler
from handlers.onboarding import OnboardingHandler
from handlers.owner import OwnerHandler
from handlers.client import ClientHandler

class WebhookRouter:
    @staticmethod
    async def route(event: InboundEvent, db) -> None:
        """Route the inbound event to the appropriate handler."""
        # Wait, the router logic will be inside webhooks.py
        pass
