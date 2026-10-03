"""Report jobs: created by the API, processed in the background by a Celery worker."""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Report, ReportKind, ReportStatus, Role, User
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)

PRIVILEGED = {Role.ADMIN, Role.MANAGER}


class ReportNotAllowed(Exception):
    pass


def can_request(user: User, kind: ReportKind) -> bool:
    return kind is not ReportKind.TEAM_OVERVIEW or user.role in PRIVILEGED


def can_view(user: User, report: Report) -> bool:
    return report.owner_id == user.id or user.role is Role.ADMIN


async def create_report(db: AsyncSession, owner: User, kind: ReportKind) -> Report:
    if not can_request(owner, kind):
        raise ReportNotAllowed
    report = Report(owner_id=owner.id, kind=kind, status=ReportStatus.PENDING)
    db.add(report)
    await db.commit()
    return report


async def mark_failed(db: AsyncSession, report: Report, message: str) -> None:
    report.status = ReportStatus.FAILED
    report.error = message[:500]
    report.completed_at = utcnow()
    await db.commit()


async def list_reports(
    db: AsyncSession, viewer: User, *, limit: int, offset: int
) -> tuple[list[Report], int]:
    """Admins see every report; everyone else sees only their own."""
    query = select(Report)
    count_query = select(func.count()).select_from(Report)
    if viewer.role is not Role.ADMIN:
        query = query.where(Report.owner_id == viewer.id)
        count_query = count_query.where(Report.owner_id == viewer.id)
    total = await db.scalar(count_query) or 0
    rows = await db.scalars(
        query.order_by(Report.created_at.desc(), Report.id).limit(limit).offset(offset)
    )
    return list(rows), total


async def _build_result(db: AsyncSession, report: Report) -> dict[str, Any]:
    if report.kind is ReportKind.MY_ACTIVITY:
        owner = await db.get(User, report.owner_id)
        if owner is None:
            raise LookupError("Report owner no longer exists")
        reports_requested = await db.scalar(
            select(func.count()).select_from(Report).where(Report.owner_id == owner.id)
        )
        created = (
            owner.created_at
            if owner.created_at.tzinfo
            else owner.created_at.replace(tzinfo=utcnow().tzinfo)
        )
        return {
            "account_age_days": (utcnow() - created).days,
            "role": owner.role.value,
            "reports_requested": reports_requested or 0,
        }

    # TEAM_OVERVIEW
    by_role = dict((await db.execute(select(User.role, func.count()).group_by(User.role))).all())
    active = await db.scalar(select(func.count()).select_from(User).where(User.is_active))
    total = sum(by_role.values())
    return {
        "total_users": total,
        "active_users": active or 0,
        "inactive_users": total - (active or 0),
        "users_by_role": {role.value: by_role.get(role, 0) for role in Role},
    }


async def process_report(db: AsyncSession, report_id: uuid.UUID) -> None:
    """Run one report job. Safe to call twice: only PENDING reports are processed."""
    report = await db.get(Report, report_id)
    if report is None or report.status is not ReportStatus.PENDING:
        logger.info("Skipping report %s (missing or already processed)", report_id)
        return

    report.status = ReportStatus.RUNNING
    await db.commit()
    try:
        report.result = await _build_result(db, report)
    except Exception:
        logger.exception("Report %s failed", report_id)
        await db.rollback()
        await db.refresh(report)  # rollback expires the instance; reload before updating it
        await mark_failed(db, report, "Report generation failed. Please try again.")
        return
    report.status = ReportStatus.COMPLETED
    report.completed_at = utcnow()
    await db.commit()
    logger.info("Report %s completed", report_id)
