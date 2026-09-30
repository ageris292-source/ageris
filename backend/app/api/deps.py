"""Shared API dependencies: DB session and authenticated user."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

DbSession = Annotated[Session, Depends(get_db)]

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_authenticated_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """Any valid session, including one that still has to replace a temporary password."""
    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(claims["sub"])
        version = int(claims.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise _UNAUTHORIZED from None
    user = db.get(User, user_id)
    if user is None or not user.is_active or version != user.token_version:
        raise _UNAUTHORIZED
    return user


AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]


def get_current_user(user: AuthenticatedUser) -> User:
    """A fully set-up user. A temporary password must be replaced first."""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password change required: set a new password to continue",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
