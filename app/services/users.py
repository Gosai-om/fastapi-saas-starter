"""User business logic. Routes stay thin; rules live here so they can be tested directly."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password_constant_time
from app.models import Role, User
from app.schemas import UserCreate

logger = logging.getLogger(__name__)


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class AccountDisabled(Exception):
    pass


class SelfModificationError(Exception):
    """Admins may not demote or deactivate themselves (prevents locking everyone out)."""


async def register_user(db: AsyncSession, data: UserCreate, role: Role = Role.USER) -> User:
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=role,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise EmailAlreadyRegistered from exc
    logger.info("User registered id=%s role=%s", user.id, user.role)  # no email in logs
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if not verify_password_constant_time(password, user.hashed_password if user else None):
        raise InvalidCredentials
    assert user is not None  # narrowed by the check above
    if not user.is_active:
        raise AccountDisabled
    return user


async def list_users(
    db: AsyncSession, *, limit: int, offset: int, role: Role | None = None
) -> tuple[list[User], int]:
    query = select(User)
    count_query = select(func.count()).select_from(User)
    if role is not None:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    total = await db.scalar(count_query) or 0
    rows = await db.scalars(query.order_by(User.created_at, User.id).limit(limit).offset(offset))
    return list(rows), total


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def change_role(db: AsyncSession, actor: User, target: User, role: Role) -> User:
    if actor.id == target.id:
        raise SelfModificationError("You cannot change your own role")
    target.role = role
    await db.commit()
    logger.info("Role changed target=%s role=%s by=%s", target.id, role, actor.id)
    return target


async def set_active(db: AsyncSession, actor: User, target: User, is_active: bool) -> User:
    if actor.id == target.id:
        raise SelfModificationError("You cannot change your own account status")
    target.is_active = is_active
    await db.commit()
    logger.info("Status changed target=%s active=%s by=%s", target.id, is_active, actor.id)
    return target
