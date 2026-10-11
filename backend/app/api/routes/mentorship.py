"""Mentorship offers: someone volunteers to help, the founder decides.

    POST   /api/mentorship/offers                 offer to mentor a company
    GET    /api/mentorship/offers/mine            offers I have made
    GET    /api/mentorship/startups/{id}/offers   offers to my company (founder)
    POST   /api/mentorship/offers/{id}/decide     accept or decline (founder)
    DELETE /api/mentorship/offers/{id}            withdraw (mentor)
    GET    /api/mentorship/startups/{id}/mentors  public mentors, anyone

Deliberately outside the marketplace: advice is not a security, so none of the
KYC, accreditation or right-of-first-refusal machinery applies. What does
apply is consent --- an offer is private between the two parties until the
founder accepts it *and* chooses to show it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, optional_user
from app.core.database import get_db
from app.models import AuditLog, Investor, MentorshipOffer, Startup, User

router = APIRouter(prefix="/api/mentorship", tags=["mentorship"])

FOCUS_AREAS = [
    "Go-to-market", "Hiring", "Fundraising", "Product", "Engineering",
    "Pricing", "Compliance", "Operations", "Marketing", "Sales",
]


class OfferIn(BaseModel):
    startup_id: str
    message: str | None = Field(None, max_length=1200)
    focus_areas: list[str] = Field(default_factory=list, max_length=6)
    hours_per_month: int | None = Field(None, ge=1, le=80)


class DecideIn(BaseModel):
    accept: bool
    # Shown on the company's public profile only if the founder says so.
    public: bool = False
    founder_note: str | None = Field(None, max_length=600)


def _mentor_out(db: Session, offer: MentorshipOffer, *, viewer: str) -> dict[str, Any]:
    """`viewer` is 'public', 'founder' or 'mentor' --- it decides how much shows."""
    user = db.get(User, offer.mentor_user_id)
    investor = db.get(Investor, user.investor_id) if user and user.investor_id else None
    out: dict[str, Any] = {
        "offer_id": offer.offer_id,
        "startup_id": offer.startup_id,
        "mentor_name": user.name if user else "Unknown",
        "mentor_firm": investor.firm_name if investor else None,
        "focus_areas": offer.focus_areas or [],
        "status": offer.status,
        "public": offer.public,
        "created_at": offer.created_at,
        "decided_at": offer.decided_at,
    }
    if viewer in ("founder", "mentor"):
        out |= {
            "message": offer.message,
            "hours_per_month": offer.hours_per_month,
            "founder_note": offer.founder_note,
            # An email is contact detail: it reaches the founder only once they
            # have accepted, and the mentor always sees their own.
            "mentor_email": user.email if user and (viewer == "mentor"
                                                    or offer.status == "accepted") else None,
        }
    return out


def _owned_startup(db: Session, startup_id: str, user: User) -> Startup:
    s = db.get(Startup, startup_id)
    if not s:
        raise HTTPException(404, "Startup not found")
    if s.owner_user_id != user.user_id:
        raise HTTPException(403, "That company belongs to someone else")
    return s


@router.get("/focus-areas")
def focus_areas():
    return {"focus_areas": FOCUS_AREAS}


@router.post("/offers", status_code=201)
def make_offer(payload: OfferIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.get(Startup, payload.startup_id)
    if not s:
        raise HTTPException(404, "Startup not found")
    if s.owner_user_id == user.user_id:
        raise HTTPException(422, "You can't offer to mentor your own company")
    if not s.owner_user_id:
        raise HTTPException(
            422,
            "No one has claimed this company yet, so there is nobody to accept. "
            "Mentorship offers go to companies whose founder is on VentureIQ.",
        )

    existing = (
        db.query(MentorshipOffer)
        .filter(
            MentorshipOffer.startup_id == payload.startup_id,
            MentorshipOffer.mentor_user_id == user.user_id,
        )
        .first()
    )
    if existing and existing.status in ("offered", "accepted"):
        raise HTTPException(409, f"You already have a {existing.status} offer with this company")

    unknown = [a for a in payload.focus_areas if a not in FOCUS_AREAS]
    if unknown:
        raise HTTPException(422, f"Unknown focus area(s): {', '.join(unknown)}")

    if existing:  # declined or withdrawn before: let them try again
        offer = existing
        offer.status = "offered"
        offer.decided_at = None
        offer.founder_note = None
        offer.public = False
    else:
        offer = MentorshipOffer(startup_id=payload.startup_id, mentor_user_id=user.user_id)
        db.add(offer)
    offer.message = payload.message
    offer.focus_areas = payload.focus_areas
    offer.hours_per_month = payload.hours_per_month

    db.flush()
    db.add(AuditLog(actor_id=user.user_id, action="mentorship.offered", entity_type="startup",
                    entity_id=payload.startup_id, detail={"offer_id": offer.offer_id}))
    db.commit()
    db.refresh(offer)
    return _mentor_out(db, offer, viewer="mentor")


@router.get("/offers/mine")
def my_offers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = (
        db.query(MentorshipOffer)
        .filter(MentorshipOffer.mentor_user_id == user.user_id)
        .order_by(MentorshipOffer.created_at.desc())
        .all()
    )
    out = []
    for offer in rows:
        s = db.get(Startup, offer.startup_id)
        out.append({**_mentor_out(db, offer, viewer="mentor"),
                    "startup_name": s.legal_name if s else None,
                    "startup_sector": s.sector if s else None})
    return out


@router.get("/startups/{startup_id}/offers")
def offers_for_my_startup(
    startup_id: str,
    status: str | None = Query(None, pattern="^(offered|accepted|declined)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _owned_startup(db, startup_id, user)
    q = db.query(MentorshipOffer).filter(MentorshipOffer.startup_id == startup_id)
    if status:
        q = q.filter(MentorshipOffer.status == status)
    rows = q.order_by(MentorshipOffer.created_at.desc()).all()
    return [_mentor_out(db, o, viewer="founder") for o in rows]


@router.post("/offers/{offer_id}/decide")
def decide(offer_id: str, payload: DecideIn, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    offer = db.get(MentorshipOffer, offer_id)
    if not offer:
        raise HTTPException(404, "No such offer")
    _owned_startup(db, offer.startup_id, user)
    if offer.status not in ("offered", "accepted"):
        raise HTTPException(409, f"This offer is already {offer.status}")

    offer.status = "accepted" if payload.accept else "declined"
    # Only an accepted mentor can be public; declining hides it either way.
    offer.public = bool(payload.accept and payload.public)
    offer.founder_note = payload.founder_note
    offer.decided_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(AuditLog(actor_id=user.user_id, action=f"mentorship.{offer.status}",
                    entity_type="startup", entity_id=offer.startup_id,
                    detail={"offer_id": offer.offer_id, "public": offer.public}))
    db.commit()
    db.refresh(offer)
    return _mentor_out(db, offer, viewer="founder")


@router.patch("/offers/{offer_id}/visibility")
def set_visibility(offer_id: str, public: bool, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """The founder can show or hide an accepted mentor at any time."""
    offer = db.get(MentorshipOffer, offer_id)
    if not offer:
        raise HTTPException(404, "No such offer")
    _owned_startup(db, offer.startup_id, user)
    if offer.status != "accepted":
        raise HTTPException(409, "Only an accepted mentor can be shown on the profile")
    offer.public = public
    db.commit()
    db.refresh(offer)
    return _mentor_out(db, offer, viewer="founder")


@router.delete("/offers/{offer_id}", status_code=204)
def withdraw(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer = db.get(MentorshipOffer, offer_id)
    if not offer:
        raise HTTPException(404, "No such offer")
    if offer.mentor_user_id != user.user_id:
        raise HTTPException(403, "That offer is someone else's")
    offer.status = "withdrawn"
    offer.public = False
    offer.decided_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()


@router.get("/startups/{startup_id}/mentors")
def public_mentors(startup_id: str, db: Session = Depends(get_db),
                   user: User | None = Depends(optional_user)):
    """Who is publicly mentoring this company.

    Anyone can read this, which is the point: a named mentor is a credibility
    signal an investor can act on. Offers the founder has not accepted, or has
    accepted privately, never appear here --- including to the mentor, who
    reads their own through `/offers/mine`.
    """
    rows = (
        db.query(MentorshipOffer)
        .filter(
            MentorshipOffer.startup_id == startup_id,
            MentorshipOffer.status == "accepted",
            MentorshipOffer.public.is_(True),
        )
        .order_by(MentorshipOffer.decided_at.asc())
        .all()
    )
    out = [_mentor_out(db, o, viewer="public") for o in rows]
    # Convenience for the profile page: does the signed-in viewer already have
    # an offer in flight, so the button can say "pending" instead of "offer".
    mine = None
    if user:
        existing = (
            db.query(MentorshipOffer)
            .filter(
                MentorshipOffer.startup_id == startup_id,
                MentorshipOffer.mentor_user_id == user.user_id,
            )
            .first()
        )
        mine = _mentor_out(db, existing, viewer="mentor") if existing else None
    return {"mentors": out, "my_offer": mine}
