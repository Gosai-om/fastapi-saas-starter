"""Import every model here so `Base.metadata` is complete for Alembic and table creation."""

from app.models.report import Report, ReportKind, ReportStatus
from app.models.user import Role, User

__all__ = ["Report", "ReportKind", "ReportStatus", "Role", "User"]
