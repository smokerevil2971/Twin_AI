from fastapi import Response
from handlers.event import InboundEvent
from handlers.client_session import ClientSessionHandler
from handlers.client_message import ClientMessageHandler

class ClientHandler:
    @staticmethod
    async def handle(event: InboundEvent, db) -> Response:
        """Route client event through session commands or RAG bot."""
        # 1. Try session handler (STOP, START, MENU, CATALOGUE, etc.)
        session_resp = await ClientSessionHandler.handle(event, db)
        if session_resp is not None:
            return session_resp

        # 2. Fall back to RAG bot / Menu flow
        return await ClientMessageHandler.handle(event, db)
