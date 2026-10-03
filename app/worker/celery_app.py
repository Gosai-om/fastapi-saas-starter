"""Celery application. Start a worker with:  celery -A app.worker.celery_app worker -l info"""

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging


def create_celery() -> Celery:
    settings = get_settings()
    configure_logging(settings.log_level)
    # No result backend: job status lives in the database (reports.status), which the API reads.
    app = Celery("saas_starter", broker=settings.redis_url, include=["app.worker.tasks"])
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        task_acks_late=True,  # a crashed worker does not lose the job
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        # Fail fast when Redis is unreachable, so the API can answer 503 instead of hanging.
        broker_connection_timeout=3,
        broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 5},
        task_publish_retry_policy={
            "max_retries": 1,
            "interval_start": 0,
            "interval_step": 0.5,
            "interval_max": 1,
        },
    )
    return app


celery_app = create_celery()
