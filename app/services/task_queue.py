"""Thin gateway between the API and Celery.

Routes depend on `get_task_queue`, so tests can swap in a fake queue and run without Redis.
"""

import uuid
from typing import Protocol


class TaskQueue(Protocol):
    def enqueue_report(self, report_id: uuid.UUID) -> None: ...

    def enqueue_welcome_email(self, user_id: uuid.UUID) -> None: ...


class CeleryTaskQueue:
    def enqueue_report(self, report_id: uuid.UUID) -> None:
        from app.worker.tasks import generate_report

        generate_report.delay(str(report_id))

    def enqueue_welcome_email(self, user_id: uuid.UUID) -> None:
        from app.worker.tasks import send_welcome_email

        send_welcome_email.delay(str(user_id))


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()
