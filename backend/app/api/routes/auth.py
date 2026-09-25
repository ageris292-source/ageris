from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import RateLimitUnavailableError, hit
from app.core.security import create_access_token
from app.core.settings import get_settings
from app.schemas import TokenResponse, UserOut
from app.services.audit import record_audit
from app.services.users import authenticate

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

    record_audit(db, action="auth.login", actor_user_id=user.id, details={"client": client})
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        expires_in_seconds=get_settings().access_token_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut(email=user.email, role=user.role.value)
