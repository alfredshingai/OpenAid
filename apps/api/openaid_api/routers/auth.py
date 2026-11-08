"""Authentication router: register, login, me + role dependencies.

The first registered account becomes admin (bootstrap); later registrations
are contributors. Roles can only be changed by an admin (out of Phase-2
scope to manage via UI; direct DB/admin tooling for now).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openaid_core.config import get_settings
from openaid_core.db import get_db
from openaid_core.governance.auth import create_token, decode_token, hash_password, verify_password
from openaid_core.governance.models import User, UserRole
from openaid_core.governance.service import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    role: str

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
        )


def _user_from_token(session: Session, authorization: str | None) -> User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token, get_settings().secret_key)
    if payload is None:
        return None
    return session.execute(
        select(User).where(User.id == payload.get("sub"), User.is_active.is_(True))
    ).scalar_one_or_none()


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_db),
) -> User | None:
    return _user_from_token(session, authorization)


def require_role(*roles: UserRole):
    """Dependency factory: 401 unauthenticated, 403 without one of ``roles``."""

    def dependency(
        authorization: Annotated[str | None, Header()] = None,
        session: Session = Depends(get_db),
    ) -> User:
        user = _user_from_token(session, authorization)
        if user is None:
            raise HTTPException(status_code=401, detail="authentication required")
        user_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        allowed = {r.value if hasattr(r, "value") else str(r) for r in roles}
        if user_role not in allowed:
            raise HTTPException(status_code=403, detail=f"requires role in {sorted(allowed)}")
        return user

    return dependency


@router.post("/register", status_code=201)
def register(payload: RegisterIn, session: Session = Depends(get_db)) -> dict:
    existing = session.execute(
        select(User).where(User.username == payload.username)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="username already taken")
    is_first = session.execute(select(func.count(User.id))).scalar_one() == 0
    role = UserRole.admin if is_first else UserRole.contributor
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=role,
    )
    session.add(user)
    session.flush()
    record_audit(
        session, "user.registered", actor_id=user.id, entity_type="user", entity_id=str(user.id),
        detail={"username": user.username, "role": role.value, "bootstrap_admin": is_first},
    )
    token = create_token(user, get_settings().secret_key)
    return {"token": token, "user": UserOut.of(user).model_dump()}


@router.post("/login")
def login(payload: LoginIn, session: Session = Depends(get_db)) -> dict:
    user = session.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_token(user, get_settings().secret_key)
    return {"token": token, "user": UserOut.of(user).model_dump()}


@router.get("/me")
def me(user: User = Depends(require_role(UserRole.contributor, UserRole.reviewer, UserRole.admin))) -> dict:
    return UserOut.of(user).model_dump()
