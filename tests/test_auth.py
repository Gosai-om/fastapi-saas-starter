from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.models import Role

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


async def test_register_creates_user_with_user_role(client, queue):
    resp = await client.post(
        REGISTER,
        json={
            "email": " New@Example.com ",
            "full_name": "New User",
            "password": "long-enough-pass",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"  # normalised
    assert body["role"] == "user"
    assert "password" not in body and "hashed_password" not in body
    assert len(queue.welcome_emails) == 1


async def test_register_rejects_duplicate_email(client, make_user):
    await make_user(email="taken@example.com")
    resp = await client.post(
        REGISTER,
        json={"email": "taken@example.com", "full_name": "X", "password": "long-enough-pass"},
    )
    assert resp.status_code == 409


async def test_register_rejects_short_password(client):
    resp = await client.post(
        REGISTER, json={"email": "a@example.com", "full_name": "A", "password": "short"}
    )
    assert resp.status_code == 422


async def test_register_still_succeeds_when_broker_is_down(client, queue):
    queue.fail = True
    resp = await client.post(
        REGISTER,
        json={"email": "b@example.com", "full_name": "B", "password": "long-enough-pass"},
    )
    assert resp.status_code == 201


async def test_login_and_me(client, make_user, login):
    user = await make_user(Role.MANAGER)
    headers = await login(user.email)
    resp = await client.get(ME, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(user.id)
    assert resp.json()["role"] == "manager"


async def test_login_wrong_password_and_unknown_email_look_the_same(client, make_user):
    user = await make_user()
    wrong = await client.post(LOGIN, data={"username": user.email, "password": "wrong-password"})
    unknown = await client.post(
        LOGIN, data={"username": "nobody@example.com", "password": "wrong-password"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_me_requires_token(client):
    assert (await client.get(ME)).status_code == 401
    bad = await client.get(ME, headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


async def test_expired_token_is_rejected(client, make_user):
    user = await make_user()
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": past, "exp": past + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    resp = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_token_signed_with_other_key_is_rejected(client, make_user):
    user = await make_user()
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        "another-secret-key-that-is-long-enough-123",
        algorithm="HS256",
    )
    resp = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
