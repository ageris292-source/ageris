from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import AuthenticatedUser, DbSession
from app.core.rate_limit import RateLimitUnavailableError, hit
from app.core.security import create_access_token
from app.core.settings import get_settings
from app.models import User
from app.schemas import ChangePasswordRequest, TokenResponse, UserOut
from app.services.audit import record_audit
from app.services.users import UserAdminError, authenticate, change_password, record_login

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_ATTEMPTS_PER_WINDOW = 10
LOGIN_WINDOW_SECONDS = 15 * 60


@router.post("/token", response_model=TokenResponse)
def login(
    request: Request,
    db: DbSession,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    client = request.client.host if request.client else "unknown"
    try:
        allowed = hit(
            f"login:{client}:{form.username.lower()}",
            LOGIN_ATTEMPTS_PER_WINDOW,
            LOGIN_WINDOW_SECONDS,
        )
    except RateLimitUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "login temporarily unavailable"
        ) from None
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts")

    user = authenticate(db, form.username, form.password)
    if user is None:
        record_audit(
            db,
            action="auth.login_failed",
            actor_user_id=None,
            details={"email": form.username.lower(), "client": client},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    record_login(db, user)
    record_audit(db, action="auth.login", actor_user_id=user.id, details={"client": client})
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value, user.token_version),
        expires_in_seconds=get_settings().access_token_minutes * 60,
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        role=user.role.value,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("/me", response_model=UserOut)
def me(user: AuthenticatedUser) -> UserOut:
    # Deliberately reachable with a temporary password, so the app can show
    # the change-password screen.
    return _user_out(user)


@router.post("/change-password", response_model=TokenResponse)
def change_own_password(
    body: ChangePasswordRequest, db: DbSession, user: AuthenticatedUser
) -> TokenResponse:
    """Replace your own password. Older sessions stop working; a fresh token is returned."""
    try:
        change_password(db, user, body.current_password, body.new_password)
    except UserAdminError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value, user.token_version),
        expires_in_seconds=get_settings().access_token_minutes * 60,
    )
