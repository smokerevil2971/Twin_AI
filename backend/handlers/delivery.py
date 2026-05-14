from sqlalchemy import select, update, func
from core.database import get_db_context
from core.utils import utcnow
from models.models import BroadcastRecipient, Broadcast
from handlers.event import InboundEvent

from core.logging import logger

GUPSHUP_STATUS_MAP = {
    "SENT": "sent",
    "DELIVERED": "delivered",
    "READ": "read",
    "FAILED": "failed",
    "ENQUEUED": "sent",
    "SUBMITTED": "sent",
}

class DeliveryHandler:
    @staticmethod
    async def handle(event: InboundEvent) -> None:
        """Shared helper — update BroadcastRecipient status from any provider's delivery receipt."""
        provider_message_id = event.delivery_msg_id
        internal_status = event.delivery_status
        payload = event.delivery_payload

        async with get_db_context() as db:
            result = await db.execute(
                select(BroadcastRecipient).where(
                    BroadcastRecipient.provider_message_id == provider_message_id
                )
            )
            recipient = result.scalar_one_or_none()

            if not recipient:
                logger.warning(f"[DELIVERY] No recipient found for msg_id={provider_message_id}")
                return

            update_values: dict = {"status": internal_status}
            now = utcnow()

            if internal_status == "delivered" and not recipient.delivered_at:
                update_values["delivered_at"] = now
            elif internal_status == "read" and not recipient.read_at:
                update_values["read_at"] = now
                if not recipient.delivered_at:
                    update_values["delivered_at"] = now
            elif internal_status == "failed":
                error_payload = payload.get("errors", payload.get("payload", {}))
                if isinstance(error_payload, list) and error_payload:
                    update_values["failed_reason"] = str(error_payload[0].get("message", internal_status))
                else:
                    update_values["failed_reason"] = str(error_payload.get("reason", internal_status))

            await db.execute(
                update(BroadcastRecipient)
                .where(BroadcastRecipient.id == recipient.id)
                .values(**update_values)
            )

            pending_count = (
                await db.execute(
                    select(func.count())
                    .where(
                        BroadcastRecipient.broadcast_id == recipient.broadcast_id,
                        BroadcastRecipient.status.in_(["pending", "sent"])
                    )
                )
            ).scalar_one()

            if pending_count == 0:
                await db.execute(
                    update(Broadcast)
                    .where(Broadcast.id == recipient.broadcast_id)
                    .values(status="sent")
                )

            await db.commit()
