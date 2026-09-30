"""Admin user management: invite with a one-time temporary password, change
roles, deactivate, reset passwords. There is still no public sign-up."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.models import User, UserRole
from app.schemas import (
    InviteUserRequest,
    InviteUserResponse,
    UpdateUserRequest,
    UserAdminOut,
)
from app.services.users import (
    UserAdminError,
    create_user,
    generate_temporary_password,
    reset_password,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])

_ONE_TIME = (
    "Share this temporary password privately. It is shown once and is not stored in "
    "readable form; the user must replace it at first sign-in."
)


def _out(u: User) -> UserAdminOut:
    return UserAdminOut(
        id=str(u.id),
        email=u.email,
        role=u.role.value,
        is_active=u.is_active,
        must_change_password=u.must_change_password,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def _get(db: DbSession, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found") from None
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return u


@router.get("", response_model=list[UserAdminOut])
def list_users(db: DbSession, _a: AdminUser) -> list[UserAdminOut]:
    return [_out(u) for u in db.scalars(select(User).order_by(User.created_at))]


@router.post("", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED)
def invite_user(body: InviteUserRequest, db: DbSession, admin: AdminUser) -> InviteUserResponse:
    temporary = generate_temporary_password()
    try:
        u = create_user(
            db,
            body.email,
            temporary,
            UserRole(body.role),
            actor_user_id=admin.id,
            must_change_password=True,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return InviteUserResponse(user=_out(u), temporary_password=temporary, notice=_ONE_TIME)


@router.patch("/{user_id}", response_model=UserAdminOut)
def patch_user(
    user_id: str, body: UpdateUserRequest, db: DbSession, admin: AdminUser
) -> UserAdminOut:
    target = _get(db, user_id)
    try:
        update_user(
            db,
            target,
            admin,
            role=UserRole(body.role) if body.role else None,
            is_active=body.is_active,
        )
    except UserAdminError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _out(target)


@router.post("/{user_id}/reset-password", response_model=InviteUserResponse)
def reset_user_password(user_id: str, db: DbSession, admin: AdminUser) -> InviteUserResponse:
    target = _get(db, user_id)
    if target.id == admin.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "use Account settings to change your own password"
        )
    temporary = reset_password(db, target, admin)
    return InviteUserResponse(user=_out(target), temporary_password=temporary, notice=_ONE_TIME)
