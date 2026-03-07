from celery import Celery
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
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    # Beat schedule for periodic tasks
    beat_schedule={
        "deactivate-expired-offers": {
            "task": "tasks.knowledge_tasks.deactivate_expired_offers",
            "schedule": 86400.0,  # daily
        },
    },
)
