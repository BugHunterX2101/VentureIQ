"""Request-time authentication (report Layer 1).

`current_user` requires a valid token; `optional_user` lets public pages work
while still personalising for a signed-in visitor. Both re-read the user from
the database, so a token stays valid only as long as the account does.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models import User


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = _bearer(request)
    if not token:
        return None
    claims = decode_token(token)
    if not claims or not claims.get("sub"):
        return None
    user = db.get(User, claims["sub"])
    return user if user and user.is_active else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    return user


def investor_user(user: User = Depends(current_user)) -> User:
    if user.role != "investor" or not user.investor_id:
        raise HTTPException(403, "This is an investor-only area")
    return user


def owns_investor(investor_id: str, user: User) -> None:
    """Investors may only read and write their own profile and feed."""
    if user.investor_id != investor_id:
        raise HTTPException(403, "That investor profile belongs to someone else")


# Who may sign off a KYC case. A real deployment puts a compliance team here,
# or an identity provider; this stands in for one and is audited either way.
REVIEWER_EMAILS = {"compliance@ventureiq.local"}


def is_reviewer(user: User) -> bool:
    return user.role == "admin" or user.email in REVIEWER_EMAILS


def reviewer_user(user: User = Depends(current_user)) -> User:
    if not is_reviewer(user):
        raise HTTPException(403, "Only a compliance reviewer can do that")
    return user
