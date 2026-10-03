"""Background tasks. Each task opens its own short-lived database engine and session."""

import asyncio
import logging
import uuid

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.reports import process_report
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _generate(report_id: uuid.UUID) -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await process_report(session, report_id)
    finally:
        await engine.dispose()


@celery_app.task(
    name="reports.generate",
    autoretry_for=(OperationalError,),  # retry only transient database errors
    retry_backoff=True,
    max_retries=3,
)
def generate_report(report_id: str) -> None:
    asyncio.run(_generate(uuid.UUID(report_id)))


@celery_app.task(name="emails.welcome")
def send_welcome_email(user_id: str) -> None:
    # Placeholder: plug in your email provider (SES, SendGrid, SMTP...) here.
    logger.info("Welcome email would be sent to user %s", user_id)
