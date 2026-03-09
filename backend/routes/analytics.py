"""
Analytics & Dashboard stats routes — Phase 4
  GET /dashboard/stats   — KPI snapshot for the Dashboard screen
  GET /analytics         — Chart data for the Analytics screen
  GET /conversations     — Conversation list (with optional flagged/resolved filter)
  PATCH /conversations/{id}/resolve — mark conversation as resolved
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func

from core.database import get_db
from core.security import get_tenant_id
from models.models import Client, Broadcast, BroadcastRecipient, Conversation, KnowledgeBase

router = APIRouter(tags=["Analytics"])
logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


# ─── GET /dashboard/stats ─────────────────────────────────────────────────────

@router.get("/dashboard/stats")
async def dashboard_stats(tenant_id: str = Depends(get_tenant_id)):
    """KPI cards for the Dashboard overview screen."""

    async for db in get_db():
        # Total + opted-in clients
        total_clients = (await db.execute(
            select(func.count()).where(Client.tenant_id == tenant_id, Client.is_deleted == False)
        )).scalar_one()

        opted_in = (await db.execute(
            select(func.count()).where(Client.tenant_id == tenant_id, Client.opted_in == True, Client.is_deleted == False)
        )).scalar_one()

        # Broadcasts this month
        month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        broadcasts_this_month = (await db.execute(
            select(func.count()).where(Broadcast.tenant_id == tenant_id, Broadcast.created_at >= month_start)
        )).scalar_one()

        # Delivery rate
        total_sent = (await db.execute(
            select(func.count())
            .select_from(BroadcastRecipient)
            .join(Broadcast, BroadcastRecipient.broadcast_id == Broadcast.id)
            .where(Broadcast.tenant_id == tenant_id)
        )).scalar_one()
        
        total_delivered = (await db.execute(
            select(func.count())
            .select_from(BroadcastRecipient)
            .join(Broadcast, BroadcastRecipient.broadcast_id == Broadcast.id)
            .where(
                Broadcast.tenant_id == tenant_id,
                BroadcastRecipient.status.in_(["delivered", "read"])
            )
        )).scalar_one()
        delivery_rate = round((total_delivered / total_sent * 100) if total_sent else 0, 1)

        # Bot resolution rate
        total_convs   = (await db.execute(select(func.count()).where(Conversation.tenant_id == tenant_id))).scalar_one()
        flagged_count = (await db.execute(
            select(func.count()).where(Conversation.tenant_id == tenant_id, Conversation.flagged == True)
        )).scalar_one()
        bot_resolution_rate = round(((total_convs - flagged_count) / total_convs * 100) if total_convs else 0, 1)

        # Active offers in KB
        active_offers = (await db.execute(
            select(func.count()).where(
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.category == "offers",
                KnowledgeBase.is_active == True,
            )
        )).scalar_one()

        return {
            "status": "success",
            "data": {
                "total_clients": total_clients,
                "opted_in": opted_in,
                "broadcasts_this_month": broadcasts_this_month,
                "delivery_rate": delivery_rate,
                "bot_resolution_rate": bot_resolution_rate,
                "active_offers": active_offers,
                "flagged_count": flagged_count,
            },
        }


# ─── GET /analytics ───────────────────────────────────────────────────────────

@router.get("/analytics")
async def analytics(tenant_id: str = Depends(get_tenant_id)):
    """Chart data for the Analytics screen — last 30 days."""

    async for db in get_db():
        cutoff = utcnow() - timedelta(days=30)

        # ── 1. Delivery trend: daily delivery % and read % ─────────────────────
        from sqlalchemy import cast, Date as SADate, case as sa_case

        trend_rows = (await db.execute(
            select(
                cast(BroadcastRecipient.sent_at, SADate).label("date"),
                func.count().label("total"),
                func.sum(sa_case(
                    (BroadcastRecipient.status.in_(["delivered", "read"]), 1),
                    else_=0,
                )).label("delivered"),
                func.sum(sa_case(
                    (BroadcastRecipient.status == "read", 1),
                    else_=0,
                )).label("read_count"),
            )
            .select_from(BroadcastRecipient)
            .join(Broadcast, BroadcastRecipient.broadcast_id == Broadcast.id)
            .where(
                Broadcast.tenant_id == tenant_id,
                BroadcastRecipient.sent_at >= cutoff,
            )
            .group_by(cast(BroadcastRecipient.sent_at, SADate))
            .order_by(cast(BroadcastRecipient.sent_at, SADate))
        )).all()

        delivery_trend = [
            {
                "date": str(r.date),
                "delivery_rate": round(r.delivered / r.total * 100, 1) if r.total else 0,
                "read_rate":     round(r.read_count / r.total * 100, 1) if r.total else 0,
            }
            for r in trend_rows
        ]

        # ── 2. Bot stats: daily resolved vs escalated conversations ────────────
        bot_rows = (await db.execute(
            select(
                cast(Conversation.created_at, SADate).label("date"),
                func.count().label("total"),
                func.sum(sa_case((Conversation.flagged == False, 1), else_=0)).label("resolved_count"),
                func.sum(sa_case((Conversation.flagged == True,  1), else_=0)).label("escalated_count"),
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.created_at >= cutoff,
            )
            .group_by(cast(Conversation.created_at, SADate))
            .order_by(cast(Conversation.created_at, SADate))
        )).all()

        bot_stats = [
            {
                "date":            str(r.date),
                "resolved":        r.resolved_count,
                "escalated":       r.escalated_count,
                "escalation_rate": round(r.escalated_count / r.total * 100, 1) if r.total else 0,
            }
            for r in bot_rows
        ]

        # ── 3. Top 10 broadcasts by reply rate ─────────────────────────────────
        bc_rows = (await db.execute(
            select(
                Broadcast.id,
                Broadcast.name,
                func.count(BroadcastRecipient.id).label("total"),
                func.sum(sa_case(
                    (BroadcastRecipient.status.in_(["delivered", "read"]), 1),
                    else_=0,
                )).label("delivered"),
            )
            .select_from(Broadcast)
            .join(BroadcastRecipient, BroadcastRecipient.broadcast_id == Broadcast.id, isouter=True)
            .where(Broadcast.tenant_id == tenant_id)
            .group_by(Broadcast.id, Broadcast.name)
            .order_by(func.count(BroadcastRecipient.id).desc())
            .limit(10)
        )).all()

        reply_rate_by_broadcast = [
            {
                "name":       (r.name or "Unnamed")[:40],
                "reply_rate": round(r.delivered / r.total * 100, 1) if r.total else 0,
            }
            for r in bc_rows
        ]

        return {
            "status": "success",
            "data": {
                "delivery_trend":        delivery_trend,
                "bot_stats":             bot_stats,
                "reply_rate_by_broadcast": reply_rate_by_broadcast,
            },
        }


# ─── GET /conversations ───────────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(
    flagged: bool | None = None,
    resolved: bool | None = None,
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
):
    """All conversations for this tenant, optionally filtered."""

    async for db in get_db():
        q = select(Conversation).where(Conversation.tenant_id == tenant_id)
        if flagged is not None:
            q = q.where(Conversation.flagged == flagged)
        q = q.order_by(Conversation.created_at.desc()).limit(limit)
        rows = (await db.execute(q)).scalars().all()

        return {
            "status": "success",
            "data": [
                {
                    "id": str(c.id),
                    "client_id": str(c.client_id) if c.client_id else None,
                    "client_phone": None,  # joined lookup skipped for performance
                    "direction": c.direction,
                    "message": c.message,
                    "response": c.response,
                    "language": c.language,
                    "flagged": c.flagged,
                    "confidence_score": c.confidence_score,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in rows
            ],
        }


# ─── PATCH /conversations/{id}/resolve ───────────────────────────────────────

@router.patch("/conversations/{conv_id}/resolve")
async def resolve_conversation(conv_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Mark a flagged conversation as resolved."""

    async for db in get_db():
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return {"status": "error", "detail": "Conversation not found"}

        conv.flagged = False
        conv.resolved = True
        await db.commit()
        return {"status": "success", "data": {"id": conv_id, "resolved": True}}


# ─── GET /conversations/{id}/messages ────────────────────────────────────────

@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, tenant_id: str = Depends(get_tenant_id)):
    """
    Return the message thread for a single conversation.
    The Conversation row stores one inbound message + one bot response,
    so we return up to 2 message objects.
    """
    async for db in get_db():
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return {"status": "error", "detail": "Conversation not found"}

        messages = [
            {
                "id": f"{conv_id}-in",
                "sender": "client",
                "text": conv.message,
                "time": conv.created_at.isoformat() if conv.created_at else None,
                "flagged": conv.flagged,
            }
        ]
        if conv.response:
            messages.append({
                "id": f"{conv_id}-out",
                "sender": "bot",
                "text": conv.response,
                "time": conv.created_at.isoformat() if conv.created_at else None,
                "flagged": False,
            })

        return {"status": "success", "data": messages}

