"""User management. There is deliberately no public sign-up endpoint:
accounts are created by an operator via `python -m app.cli create-user`, or
by an admin in the web app (invite with a one-time temporary password)."""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import User, UserRole
from app.services.audit import record_audit

MIN_PASSWORD_LENGTH = 12


class UserAdminError(ValueError):
    """A user-management request that would break an invariant (e.g. no admin left)."""


def generate_temporary_password() -> str:
    """16 characters from an unambiguous alphabet, grouped for reading aloud."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def create_user(
    db: Session,
    email: str,
    password: str,
    role: UserRole,
    *,
    actor_user_id: uuid.UUID | None = None,
    must_change_password: bool = False,
) -> User:
    email = email.strip().lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise ValueError(f"user {email} already exists")
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=role,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        action="user.create",
        actor_user_id=actor_user_id,
        entity_type="user",
        entity_id=str(user.id),
        details={"email": email, "role": role.value},
    )
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        # Still spend hashing time so response timing does not reveal account existence.
        verify_password(password, _DUMMY_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None


_DUMMY_HASH = hash_password("aegis-timing-equaliser-not-a-real-password")


def _active_admins(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active)
        )
        or 0
    )


def record_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(UTC)


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise UserAdminError("current password is incorrect")
    if len(new) < MIN_PASSWORD_LENGTH:
        raise UserAdminError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if new == current:
        raise UserAdminError("the new password must differ from the current one")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.token_version += 1
    record_audit(
        db,
        action="user.change_password",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=str(user.id),
        details={},
    )
    db.commit()


def reset_password(db: Session, target: User, actor: User) -> str:
    """Issue a new temporary password; the user must replace it at next sign-in."""
    temporary = generate_temporary_password()
    target.password_hash = hash_password(temporary)
    target.must_change_password = True
    target.token_version += 1
    record_audit(
        db,
        action="user.reset_password",
        actor_user_id=actor.id,
        entity_type="user",
        entity_id=str(target.id),
        details={"email": target.email},
    )
    db.commit()
    return temporary


def update_user(
    db: Session,
    target: User,
    actor: User,
    *,
    role: UserRole | None = None,
    is_active: bool | None = None,
) -> User:
    """Change role / active flag. Never leaves the system without an active admin,
    and an admin cannot lock themselves out."""
    changes: dict[str, object] = {}
    if target.id == actor.id and (
        (role is not None and role is not UserRole.ADMIN) or is_active is False
    ):
        raise UserAdminError("you cannot demote or deactivate your own account")
    losing_admin = (
        target.role is UserRole.ADMIN
        and target.is_active
        and ((role is not None and role is not UserRole.ADMIN) or is_active is False)
    )
    if losing_admin and _active_admins(db) <= 1:
        raise UserAdminError("at least one active admin must remain")
    if role is not None and role is not target.role:
        changes["role"] = [target.role.value, role.value]
        target.role = role
    if is_active is not None and is_active != target.is_active:
        changes["is_active"] = [target.is_active, is_active]
        target.is_active = is_active
    if changes:
        target.token_version += 1  # sessions pick up the change immediately
        record_audit(
            db,
            action="user.update",
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=str(target.id),
            details={"email": target.email, **changes},
        )
        db.commit()
    return target
