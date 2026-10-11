"""Secondary marketplace — a complete flow, deliberately simulated.

    GET  /api/marketplace/rules                 the compliance rules, in the open
    POST /api/marketplace/listings/{id}/offers  make an offer (gated)
    GET  /api/marketplace/offers                offers I can see
    POST /api/marketplace/offers/{id}/accept    founder accepts; RoFR window opens
    POST /api/marketplace/offers/{id}/decline
    POST /api/marketplace/offers/{id}/settle    simulated escrow → settled

No money moves and no equity changes hands. Selling shares in a private company
is SEBI/RBI-regulated activity that needs licensed escrow and a registered
platform, so every endpoint refuses to pretend: responses carry `simulated:
true`, the escrow is a state machine, and each transition is audited.

What *is* real is the compliance layer: rules are declared in one place,
evaluated per offer, and the reasons are returned to the caller rather than
hidden. That is the "Compliance-as-Code" the report asks for, minus the money.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.models import AuditLog, Investor, KycCase, Listing, Offer, Startup, User

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

# A private-placement style threshold: above it we require an accredited
# investor. The number is illustrative; a real deployment takes it from the
# applicable SEBI rules and keeps it versioned.
ACCREDITED_THRESHOLD_USD = 250_000
MIN_COMPOSITE_FOR_LISTING = 40.0

RULES = [
    {"id": "kyc_verified", "rule": "The buyer's KYC case must be verified by a reviewer",
     "why": "SEBI/PMLA obligations sit on the platform, not the buyer"},
    {"id": "accredited_for_large_cheques",
     "rule": f"Offers above ${ACCREDITED_THRESHOLD_USD:,} need an accredited investor",
     "why": "Large private placements are restricted to accredited investors"},
    {"id": "no_self_dealing", "rule": "A founder cannot bid on their own company",
     "why": "Obvious conflict of interest"},
    {"id": "listing_open", "rule": "The listing must still be open",
     "why": "An accepted listing is under a right-of-first-refusal window"},
    {"id": "company_not_flagged",
     "rule": f"The company must be scored and not below composite {MIN_COMPOSITE_FOR_LISTING:.0f}",
     "why": "Unscored or badly-flagged companies should not be traded on this platform"},
    {"id": "rofr", "rule": "Existing holders get a right-of-first-refusal window before settlement",
     "why": "Standard in private secondaries, and usually a charter obligation"},
]


class OfferIn(BaseModel):
    amount: float = Field(gt=0, le=1e9)
    equity_pct: float | None = Field(None, gt=0, le=100)
    message: str | None = Field(None, max_length=1000)


def _evaluate(db: Session, user: User, listing: Listing, startup: Startup,
              amount: float) -> list[dict[str, Any]]:
    """Run every rule and return each verdict, pass or fail."""
    investor = db.get(Investor, user.investor_id) if user.investor_id else None
    kyc = (
        db.query(KycCase)
        .filter(KycCase.user_id == user.user_id)
        .order_by(KycCase.submitted_at.desc())
        .first()
    )
    score = startup.latest_score

    verdicts = [
        {"id": "kyc_verified",
         "passed": bool(kyc and kyc.status == "verified"),
         "detail": f"KYC is {kyc.status if kyc else 'not started'}"},
        {"id": "accredited_for_large_cheques",
         "passed": amount <= ACCREDITED_THRESHOLD_USD or bool(investor and investor.accredited_investor),
         "detail": (f"${amount:,.0f} is within the ${ACCREDITED_THRESHOLD_USD:,} limit"
                    if amount <= ACCREDITED_THRESHOLD_USD
                    else f"${amount:,.0f} needs an accredited investor"
                         f" ({'accredited' if investor and investor.accredited_investor else 'not accredited'})")},
        {"id": "no_self_dealing",
         "passed": startup.owner_user_id != user.user_id,
         "detail": "You registered this company" if startup.owner_user_id == user.user_id else "Not your company"},
        {"id": "listing_open",
         "passed": listing.status == "open",
         "detail": f"Listing is {listing.status}"},
        {"id": "company_not_flagged",
         "passed": bool(score and (score.composite_score or 0) >= MIN_COMPOSITE_FOR_LISTING),
         "detail": (f"Composite {score.composite_score:.1f}" if score else "Not scored yet")},
    ]
    for v in verdicts:
        rule = next(r for r in RULES if r["id"] == v["id"])
        v["rule"] = rule["rule"]
        v["why"] = rule["why"]
    return verdicts


def _offer_out(offer: Offer, listing: Listing | None = None,
               startup: Startup | None = None) -> dict[str, Any]:
    return {
        "offer_id": offer.offer_id,
        "listing_id": offer.listing_id,
        "investor_id": offer.investor_id,
        "amount": offer.amount,
        "equity_pct": offer.equity_pct,
        "message": offer.message,
        "status": offer.status,
        "compliance": offer.compliance,
        "rofr_expires_at": offer.rofr_expires_at,
        "created_at": offer.created_at,
        "simulated": True,
        "startup": {"startup_id": startup.startup_id, "legal_name": startup.legal_name}
        if startup else None,
        "ask_amount": listing.ask_amount if listing else None,
    }


@router.get("/rules")
def rules():
    """Published so nobody has to read the code to know what is enforced."""
    return {
        "simulated": True,
        "disclaimer": "No money moves and no equity is transferred. Escrow here is a state "
                      "machine standing in for a licensed provider.",
        "accredited_threshold_usd": ACCREDITED_THRESHOLD_USD,
        "min_composite_for_listing": MIN_COMPOSITE_FOR_LISTING,
        "rules": RULES,
    }


@router.post("/listings/{listing_id}/offers", status_code=201)
def make_offer(listing_id: str, payload: OfferIn, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    if user.role != "investor" or not user.investor_id:
        raise HTTPException(403, "Only investor accounts can make offers")
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(404, "No such listing")
    startup = db.get(Startup, listing.startup_id)

    verdicts = _evaluate(db, user, listing, startup, payload.amount)
    blocked = [v for v in verdicts if not v["passed"]]
    if blocked:
        # 422 with the reasons, rather than a silent refusal.
        raise HTTPException(422, {"message": "This offer doesn't meet the platform's rules",
                                  "failed": blocked, "simulated": True})

    offer = Offer(listing_id=listing_id, investor_id=user.investor_id, user_id=user.user_id,
                  amount=payload.amount, equity_pct=payload.equity_pct, message=payload.message,
                  compliance={"evaluated_at": datetime.now(UTC).isoformat(), "verdicts": verdicts})
    db.add(offer)
    db.add(AuditLog(actor_id=user.user_id, action="offer.created", entity_type="offer",
                    entity_id=offer.offer_id,
                    detail={"listing_id": listing_id, "amount": payload.amount, "simulated": True}))
    db.commit()
    db.refresh(offer)
    return _offer_out(offer, listing, startup)


@router.get("/offers")
def my_offers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """An investor sees their own offers; a founder sees offers on their companies."""
    query = db.query(Offer, Listing, Startup).join(
        Listing, Listing.listing_id == Offer.listing_id).join(
        Startup, Startup.startup_id == Listing.startup_id)
    if user.role == "founder":
        query = query.filter(Startup.owner_user_id == user.user_id)
    else:
        query = query.filter(Offer.user_id == user.user_id)
    return [_offer_out(o, ls, s) for o, ls, s in query.order_by(Offer.created_at.desc()).limit(50)]


def _load_for_founder(db: Session, offer_id: str, user: User) -> tuple[Offer, Listing, Startup]:
    row = (
        db.query(Offer, Listing, Startup)
        .join(Listing, Listing.listing_id == Offer.listing_id)
        .join(Startup, Startup.startup_id == Listing.startup_id)
        .filter(Offer.offer_id == offer_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "No such offer")
    offer, listing, startup = row
    if startup.owner_user_id != user.user_id:
        raise HTTPException(403, "Only the founder of this company can act on its offers")
    return offer, listing, startup


@router.post("/offers/{offer_id}/accept")
def accept(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer, listing, startup = _load_for_founder(db, offer_id, user)
    if offer.status != "offered":
        raise HTTPException(409, f"This offer is already {offer.status}")
    offer.status = "rofr_window"
    offer.rofr_expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=listing.rofr_days)
    listing.status = "under_offer"
    db.add(AuditLog(actor_id=user.user_id, action="offer.accepted", entity_type="offer",
                    entity_id=offer.offer_id,
                    detail={"rofr_days": listing.rofr_days, "simulated": True}))
    db.commit()
    db.refresh(offer)
    return {**_offer_out(offer, listing, startup),
            "next": "Existing holders may exercise their right of first refusal until "
                    f"{offer.rofr_expires_at:%Y-%m-%d}. After that the offer can be settled."}


@router.post("/offers/{offer_id}/decline")
def decline(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    offer, listing, startup = _load_for_founder(db, offer_id, user)
    if offer.status not in ("offered", "rofr_window"):
        raise HTTPException(409, f"This offer is already {offer.status}")
    offer.status = "declined"
    listing.status = "open"
    db.add(AuditLog(actor_id=user.user_id, action="offer.declined", entity_type="offer",
                    entity_id=offer.offer_id, detail={"simulated": True}))
    db.commit()
    db.refresh(offer)
    return _offer_out(offer, listing, startup)


@router.post("/offers/{offer_id}/settle")
def settle(offer_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Simulated settlement. Refuses while the RoFR window is open."""
    offer, listing, startup = _load_for_founder(db, offer_id, user)
    if offer.status != "rofr_window":
        raise HTTPException(409, f"This offer is {offer.status}; only an accepted offer settles")
    now = datetime.now(UTC).replace(tzinfo=None)
    if offer.rofr_expires_at and now < offer.rofr_expires_at:
        raise HTTPException(409, {
            "message": "The right-of-first-refusal window is still open",
            "until": offer.rofr_expires_at.isoformat(), "simulated": True})
    offer.status = "settled_simulated"
    listing.status = "closed"
    db.add(AuditLog(actor_id=user.user_id, action="offer.settled_simulated", entity_type="offer",
                    entity_id=offer.offer_id,
                    detail={"amount": offer.amount, "simulated": True,
                            "note": "No funds moved. A licensed escrow provider would settle here."}))
    db.commit()
    db.refresh(offer)
    return {**_offer_out(offer, listing, startup),
            "settlement": {"simulated": True, "escrow_provider": None,
                           "note": "Recorded as settled for demonstration only. No money moved, "
                                   "no share transfer was filed."}}
