"""Password hashing (Argon2) and JWT access tokens."""

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

_password_hash = PasswordHash.recommended()  # Argon2id with library-recommended parameters


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hash.verify(password, hashed)


@lru_cache
def _dummy_hash() -> str:
    return _password_hash.hash("timing-equaliser-not-a-real-password")


def verify_password_constant_time(password: str, hashed: str | None) -> bool:
    """Verify a password, spending the same time whether or not the user exists.

    Without this, a login for an unknown email returns faster than one with a wrong
    password, which lets an attacker discover which emails are registered.
    """
    if hashed is None:
        _password_hash.verify(password, _dummy_hash())
        return False
    return verify_password(password, hashed)


def create_access_token(subject: uuid.UUID, settings: Settings) -> str:
    """Issue a short-lived access token. The token carries only the user id; role and
    active status are always read from the database, so changes apply immediately."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Return the user id from a valid access token.

    Raises:
        jwt.PyJWTError: the token is malformed, expired or signed with another key.
        ValueError: the token is valid JWT but not an access token for a user id.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )
    if payload.get("type") != "access":
        raise ValueError("Not an access token")
    return uuid.UUID(payload["sub"])
