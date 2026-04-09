from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "twinai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "tasks.broadcast_tasks",
        "tasks.knowledge_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.timezone,
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "deactivate-expired-offers": {
            "task": "tasks.knowledge_tasks.deactivate_expired_offers",
            "schedule": settings.kb_expiry_check_interval_seconds,
        },
        "send-flagged-digest": {
            "task": "tasks.broadcast_tasks.send_flagged_digest",
            "schedule": settings.flagged_digest_hours * 3600,
        },
        # 2.6: Daily new-client digest — runs at 9 PM IST (15:30 UTC)
        "send-new-client-digest": {
            "task": "tasks.broadcast_tasks.send_new_client_digest",
            "schedule": crontab(hour=15, minute=30),  # 9:00 PM IST
        },
        # 3.5: Offer expiry alert — runs at 8 AM IST (2:30 AM UTC)
        "check-expiring-offers": {
            "task": "tasks.broadcast_tasks.check_expiring_offers",
            "schedule": crontab(hour=2, minute=30),   # 8:00 AM IST
        },
    },
)
