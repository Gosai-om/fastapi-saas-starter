import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from starlette.concurrency import run_in_threadpool

from app.api.deps import AppSettings, CurrentUser, DbSession, Queue
from app.core.security import create_access_token
from app.schemas import Token, UserCreate, UserRead
from app.services import users as user_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: DbSession, queue: Queue) -> UserRead:
    """Create an account. Public sign-ups always get the `user` role."""
    try:
        user = await user_service.register_user(db, data)
    except user_service.EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from None
    try:
        await run_in_threadpool(queue.enqueue_welcome_email, user.id)
    except Exception:  # a broker outage must not block sign-up
        logger.warning("Could not queue welcome email for user %s", user.id, exc_info=True)
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession, settings: AppSettings
) -> Token:
    """OAuth2 password flow: send `username` (your email) and `password` as form fields."""
    try:
        user = await user_service.authenticate(db, form.username, form.password)
    except user_service.InvalidCredentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except user_service.AccountDisabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled") from None
    return Token(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
