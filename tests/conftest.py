"""Test fixtures: in-memory SQLite database and a fake task queue (no Postgres or Redis needed)."""

import os

# Must be set before the app (and its cached settings) is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["LOG_LEVEL"] = "WARNING"

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Role
from app.schemas import UserCreate
from app.services.task_queue import get_task_queue
from app.services.users import register_user

PASSWORD = "correct-horse-battery"


class FakeTaskQueue:
    """Records queued jobs instead of sending them to Celery."""

    def __init__(self) -> None:
        self.reports: list[uuid.UUID] = []
        self.welcome_emails: list[uuid.UUID] = []
        self.fail = False

    def enqueue_report(self, report_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.reports.append(report_id)

    def enqueue_welcome_email(self, user_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.welcome_emails.append(user_id)


@pytest.fixture
async def sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


@pytest.fixture
def queue() -> FakeTaskQueue:
    return FakeTaskQueue()


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], queue: FakeTaskQueue
) -> AsyncIterator[AsyncClient]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_task_queue] = lambda: queue
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(sessionmaker: async_sessionmaker[AsyncSession]):
    """Create a user directly in the database and return (user, auth headers factory)."""

    async def _make(role: Role = Role.USER, email: str | None = None):
        email = email or f"{role.value}-{uuid.uuid4().hex[:8]}@example.com"
        async with sessionmaker() as session:
            return await register_user(
                session,
                UserCreate(email=email, full_name=f"Test {role.value}", password=PASSWORD),
                role=role,
            )

    return _make


@pytest.fixture
def login(client: AsyncClient):
    async def _login(email: str, password: str = PASSWORD) -> dict[str, str]:
        resp = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _login
