import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, Paging, require_roles
from app.models import Role, User
from app.schemas import Page, RoleUpdate, StatusUpdate, UserRead
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])

AdminOnly = Annotated[User, Depends(require_roles(Role.ADMIN))]
AdminOrManager = Annotated[User, Depends(require_roles(Role.ADMIN, Role.MANAGER))]


async def _get_target(db: DbSession, user_id: uuid.UUID) -> User:
    user = await user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("", response_model=Page[UserRead])
async def list_users(
    _: AdminOrManager, db: DbSession, paging: Paging, role: Role | None = None
) -> Page[UserRead]:
    """List users (admins and managers). Optional filter by role."""
    users, total = await user_service.list_users(
        db, limit=paging.limit, offset=paging.offset, role=role
    )
    return Page[UserRead](
        items=[UserRead.model_validate(u) for u in users],
        total=total,
        limit=paging.limit,
        offset=paging.offset,
    )


@router.patch("/{user_id}/role", response_model=UserRead)
async def change_role(
    user_id: uuid.UUID, body: RoleUpdate, admin: AdminOnly, db: DbSession
) -> UserRead:
    """Change a user's role (admins only; you cannot change your own)."""
    target = await _get_target(db, user_id)
    try:
        user = await user_service.change_role(db, admin, target, body.role)
    except user_service.SelfModificationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return UserRead.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserRead)
async def change_status(
    user_id: uuid.UUID, body: StatusUpdate, admin: AdminOnly, db: DbSession
) -> UserRead:
    """Activate or deactivate a user (admins only). Deactivation takes effect immediately."""
    target = await _get_target(db, user_id)
    try:
        user = await user_service.set_active(db, admin, target, body.is_active)
    except user_service.SelfModificationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return UserRead.model_validate(user)
