import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DbSession, Paging, Queue
from app.models import Report
from app.schemas import Page, ReportCreate, ReportRead
from app.services import reports as report_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportRead, status_code=status.HTTP_202_ACCEPTED)
async def request_report(
    body: ReportCreate, user: CurrentUser, db: DbSession, queue: Queue
) -> ReportRead:
    """Queue a report. Poll `GET /reports/{id}` until its status is `completed`."""
    try:
        report = await report_service.create_report(db, user, body.kind)
    except report_service.ReportNotAllowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only managers and admins can request this report"
        ) from None
    try:
        await run_in_threadpool(queue.enqueue_report, report.id)
    except Exception:
        logger.exception("Could not queue report %s", report.id)
        await report_service.mark_failed(db, report, "Could not queue the job. Please retry.")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Background workers are unavailable"
        ) from None
    return ReportRead.model_validate(report)


@router.get("", response_model=Page[ReportRead])
async def list_reports(user: CurrentUser, db: DbSession, paging: Paging) -> Page[ReportRead]:
    """Your reports, newest first (admins see everyone's)."""
    reports, total = await report_service.list_reports(
        db, user, limit=paging.limit, offset=paging.offset
    )
    return Page[ReportRead](
        items=[ReportRead.model_validate(r) for r in reports],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ReportRead:
    report = await db.get(Report, report_id)
    # 404 (not 403) for other people's reports, so ids cannot be probed.
    if report is None or not report_service.can_view(user, report):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return ReportRead.model_validate(report)
