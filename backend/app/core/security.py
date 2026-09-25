"""Password hashing (Argon2id) and JWT access tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.settings import get_settings

_hasher = PasswordHasher()
_TOKEN_AUDIENCE = "aegis-api"  # noqa: S105  (JWT audience, not a secret)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "aud": _TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any invalid, expired or tampered token."""
    s = get_settings()
    return jwt.decode(
        token,
        s.jwt_secret.get_secret_value(),
        algorithms=[s.jwt_algorithm],
        audience=_TOKEN_AUDIENCE,
        options={"require": ["exp", "sub", "aud"]},
    )
