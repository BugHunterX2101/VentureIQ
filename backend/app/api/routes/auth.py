"""Accounts, sign-in and the signed-in user's own data.

    POST /api/auth/register          create an account (investor or founder)
    POST /api/auth/login             email + password → JWT
    GET  /api/auth/me                the signed-in user, investor and counts
    PATCH /api/auth/me               change name or password
    GET/POST/PATCH/DELETE /api/auth/me/watchlist   companies I'm tracking

An investor account owns exactly one `investor` row, created here so the feed
and matching have a mandate to work with from the first login.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user, is_reviewer
from app.core.database import get_db
from app.core.security import (
    MAX_PASSWORD_BYTES,
    clear_failed_logins,
    create_access_token,
    hash_password,
    login_blocked,
    record_failed_login,
    verify_password,
)
from app.models import AuditLog, BehavioralEvent, Investor, InvestorPreference, Startup, User, WatchlistItem

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=160)
    role: Literal["investor", "founder"] = "investor"
    # Investor-only, all optional: the full mandate is set in onboarding.
    investor_type: Literal["angel", "vc_fund", "family_office"] = "angel"
    firm_name: str | None = Field(None, max_length=200)

    @field_validator("password")
    @classmethod
    def fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
        return v

    @field_validator("email")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.strip().lower()


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.strip().lower()


class UpdateMeIn(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=160)
    current_password: str | None = Field(None, max_length=128)
    new_password: str | None = Field(None, min_length=8, max_length=128)


class WatchIn(BaseModel):
    startup_id: str
    note: str | None = Field(None, max_length=2000)
    stage: Literal["watching", "contacted", "passed"] = "watching"


def _user_out(db: Session, user: User) -> dict[str, Any]:
    investor = db.get(Investor, user.investor_id) if user.investor_id else None
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "investor_id": user.investor_id,
        "investor_name": investor.name if investor else None,
        "kyc_status": investor.kyc_status if investor else None,
        "has_mandate": bool(investor and investor.preference),
        # Lets the UI offer the KYC queue only to whoever may act on it; the
        # endpoints check this again themselves.
        "is_reviewer": is_reviewer(user),
        "watchlist_count": db.query(WatchlistItem).filter(WatchlistItem.user_id == user.user_id).count(),
        "created_at": user.created_at,
    }


def _token_for(user: User) -> dict[str, Any]:
    return {
        "access_token": create_access_token(
            user.user_id, user.role, {"investor_id": user.investor_id, "email": user.email}
        ),
        "token_type": "bearer",
    }


@router.get("/providers")
def providers():
    """Which sign-in methods this deployment offers."""
    from app.api.routes.oauth import configured as google_configured

    return {"password": True, "google": google_configured()}


@router.post("/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(409, "An account with this email already exists")

    user = User(
        email=payload.email,
        name=payload.name.strip(),
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    if payload.role == "investor":
        investor = Investor(
            name=payload.name.strip(),
            email=payload.email,
            investor_type=payload.investor_type,
            firm_name=payload.firm_name,
        )
        db.add(investor)
        db.flush()
        user.investor_id = investor.investor_id
    db.add(user)
    db.flush()
    db.add(AuditLog(actor_id=user.user_id, action="user.registered", entity_type="user",
                    entity_id=user.user_id, detail={"role": user.role}))
    db.commit()
    db.refresh(user)
    return {**_token_for(user), "user": _user_out(db, user)}


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    # Throttle by account and by caller, so neither one account nor one client
    # can be used to guess passwords indefinitely.
    keys = (f"email:{payload.email}", f"ip:{request.client.host if request.client else '-'}")
    wait = login_blocked(*keys)
    if wait:
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(wait)},
        )

    user = db.query(User).filter(User.email == payload.email).first()
    # Same message either way: do not reveal which accounts exist.
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        record_failed_login(*keys)
        raise HTTPException(401, "Email or password is incorrect")
    if not user.is_active:
        raise HTTPException(403, "This account is disabled")
    clear_failed_logins(*keys)
    user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(user)
    return {**_token_for(user), "user": _user_out(db, user)}


@router.get("/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _user_out(db, user)


@router.patch("/me")
def update_me(payload: UpdateMeIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if payload.name:
        user.name = payload.name.strip()
    if payload.new_password:
        if not payload.current_password or not user.password_hash or not verify_password(
            payload.current_password, user.password_hash
        ):
            raise HTTPException(403, "Current password is incorrect")
        user.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


# --------------------------------------------------------------------------
# watchlist — the investor's own deal pipeline
# --------------------------------------------------------------------------


def _item_out(item: WatchlistItem) -> dict[str, Any]:
    s = item.startup
    score = s.latest_score if s else None
    return {
        "item_id": item.item_id,
        "startup_id": item.startup_id,
        "note": item.note,
        "stage": item.stage,
        "created_at": item.created_at,
        "startup": {
            "startup_id": s.startup_id,
            "legal_name": s.legal_name,
            "logo_url": s.logo_url,
            "sector": s.sector,
            "stage": s.stage,
            "hq_city": s.hq_city,
            "verified": s.verified,
            "composite_score": score.composite_score if score else None,
            "fraud_likelihood_score": score.fraud_likelihood_score if score else None,
        } if s else None,
    }


@router.get("/me/watchlist")
def list_watchlist(db: Session = Depends(get_db), user: User = Depends(current_user)):
    items = (
        db.query(WatchlistItem)
        .options(selectinload(WatchlistItem.startup).selectinload(Startup.scores))
        .filter(WatchlistItem.user_id == user.user_id)
        .order_by(WatchlistItem.created_at.desc())
        .all()
    )
    return [_item_out(i) for i in items]


@router.post("/me/watchlist", status_code=201)
def add_watchlist(payload: WatchIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not db.get(Startup, payload.startup_id):
        raise HTTPException(404, "Startup not found")
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.user_id, WatchlistItem.startup_id == payload.startup_id)
        .first()
    )
    if item:
        item.note = payload.note if payload.note is not None else item.note
        item.stage = payload.stage
    else:
        item = WatchlistItem(user_id=user.user_id, startup_id=payload.startup_id,
                             note=payload.note, stage=payload.stage)
        db.add(item)
        if user.investor_id:
            # Saving is also a behavioural signal the matcher learns from.
            db.add(BehavioralEvent(investor_id=user.investor_id, startup_id=payload.startup_id,
                                   event_type="save", event_value={"via": "watchlist"}))
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.patch("/me/watchlist/{startup_id}")
def update_watchlist(startup_id: str, payload: WatchIn, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.user_id, WatchlistItem.startup_id == startup_id)
        .first()
    )
    if not item:
        raise HTTPException(404, "Not on your watchlist")
    item.note = payload.note
    item.stage = payload.stage
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.delete("/me/watchlist/{startup_id}", status_code=204)
def remove_watchlist(startup_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.user_id == user.user_id, WatchlistItem.startup_id == startup_id)
        .first()
    )
    if item:
        db.delete(item)
        db.commit()


@router.get("/me/startups")
def my_startups(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Companies this account registered, newest first."""
    rows = (
        db.query(Startup)
        .options(selectinload(Startup.scores), selectinload(Startup.fraud_signals))
        .filter(Startup.owner_user_id == user.user_id)
        .order_by(Startup.created_at.desc())
        .all()
    )
    out = []
    for s in rows:
        score = s.latest_score
        open_flags = [f for f in s.fraud_signals if not f.reviewed_by_human]
        out.append({
            "startup_id": s.startup_id,
            "legal_name": s.legal_name,
            "sector": s.sector,
            "stage": s.stage,
            "hq_city": s.hq_city,
            "website": s.website,
            "cin": s.cin,
            "verified": s.verified,
            "created_at": s.created_at,
            "composite_score": score.composite_score if score else None,
            "growth_potential_score": score.growth_potential_score if score else None,
            "risk_level_score": score.risk_level_score if score else None,
            "fraud_likelihood_score": score.fraud_likelihood_score if score else None,
            "founder_credibility_score": score.founder_credibility_score if score else None,
            "confidence": score.confidence if score else None,
            "scored_at": score.computed_at if score else None,
            "open_flags": len(open_flags),
            "top_flag": open_flags[0].explanation if open_flags else None,
        })
    return out


@router.put("/me/mandate")
def set_mandate(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Create or replace the signed-in investor's mandate."""
    if user.role != "investor" or not user.investor_id:
        raise HTTPException(403, "Only investor accounts have a mandate")
    from app.schemas.dto import PreferenceIn

    pref_in = PreferenceIn(**payload)
    investor = db.get(Investor, user.investor_id)
    if investor.preference:
        db.delete(investor.preference)
        db.flush()
    db.add(InvestorPreference(investor_id=investor.investor_id, **pref_in.model_dump()))
    db.commit()
    return _user_out(db, user)
