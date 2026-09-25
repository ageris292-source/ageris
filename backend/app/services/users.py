"""User management. There is deliberately no public sign-up endpoint:
accounts are created by an operator via `python -m app.cli create-user`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import User, UserRole
from app.services.audit import record_audit

MIN_PASSWORD_LENGTH = 12


def create_user(db: Session, email: str, password: str, role: UserRole) -> User:
    email = email.strip().lower()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise ValueError(f"user {email} already exists")
    user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    record_audit(
        db,
        action="user.create",
        actor_user_id=None,
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
