"""Investor pipeline endpoints (report Layer 4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.api.routes.startups import _summary
from app.api.deps import current_user, owns_investor
from app.core.database import get_db
from app.ml.matching import build_feed
from app.models import AuditLog, BehavioralEvent, Investor, InvestorPreference, User
from app.schemas.dto import EventIn, InvestorIn, InvestorOut, MatchOut

router = APIRouter(prefix="/api/investors", tags=["investors"])


@router.get("/mandate/preview")
def mandate_preview(
    sectors: list[str] = Query(default_factory=list),
    stages: list[str] = Query(default_factory=list),
    cities: list[str] = Query(default_factory=list),
    db: Session = Depends(get_db),
):
    """How many companies a mandate would actually reach, right now.

    Onboarding otherwise asks an investor to fill a form and trust that
    something useful comes out of it. Counting the corpus against their
    choices as they make them turns the form into a dial they can see moving,
    and it is the same corpus the feed ranks over --- not an illustration.
    """
    from app.models import Score, Startup

    q = (
        db.query(Startup)
        .join(Score, (Score.startup_id == Startup.startup_id) & Score.is_current.is_(True))
    )
    if sectors:
        q = q.filter(Startup.sector.in_(sectors))
    if stages:
        q = q.filter(Startup.stage.in_(stages))
    if cities:
        # Geography is stored as a city, and investors think in cities here.
        q = q.filter(or_(*[Startup.hq_city.ilike(f"%{c}%") for c in cities]))

    total = q.distinct().count()
    sample = (
        q.order_by(Score.composite_score.desc())
        .distinct()
        .limit(3)
        .all()
    )
    return {
        "matches": total,
        "sample": [
            {"startup_id": s.startup_id, "legal_name": s.legal_name, "sector": s.sector,
             "hq_city": s.hq_city, "composite_score": (s.latest_score.composite_score
                                                       if s.latest_score else None)}
            for s in sample
        ],
    }


@router.get("", response_model=list[InvestorOut])
def list_investors(db: Session = Depends(get_db)):
    return (
        db.query(Investor)
        .options(selectinload(Investor.preference))
        .order_by(Investor.created_at.desc())
        .limit(100)
        .all()
    )


@router.post("", response_model=InvestorOut, status_code=201)
def create_investor(payload: InvestorIn, db: Session = Depends(get_db)):
    inv = Investor(
        name=payload.name,
        email=payload.email,
        investor_type=payload.investor_type,
        firm_name=payload.firm_name,
        sebi_registration_no=payload.sebi_registration_no,
        accredited_investor=payload.accredited_investor,
        # A real KYC provider decides this. Auto-passing here is a SIMULATION;
        # see docs/BUILD_PLAN.md Problem 1.
        kyc_status="verified" if payload.sebi_registration_no else "pending",
    )
    db.add(inv)
    db.flush()

    if payload.preference:
        db.add(
            InvestorPreference(
                investor_id=inv.investor_id, **payload.preference.model_dump()
            )
        )

    db.add(
        AuditLog(
            action="investor.created",
            entity_type="investor",
            entity_id=inv.investor_id,
            detail={"type": inv.investor_type},
        )
    )
    db.commit()
    db.refresh(inv)
    return inv


@router.get("/{investor_id}", response_model=InvestorOut)
def get_investor(investor_id: str, db: Session = Depends(get_db)):
    inv = (
        db.query(Investor)
        .options(selectinload(Investor.preference))
        .filter(Investor.investor_id == investor_id)
        .first()
    )
    if not inv:
        raise HTTPException(404, "Investor not found")
    return inv


@router.get("/{investor_id}/feed", response_model=list[MatchOut])
def feed(
    investor_id: str,
    limit: int = Query(20, ge=1, le=60),
    exclude_seen: bool = False,
    min_composite: float | None = Query(None, ge=0, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owns_investor(investor_id, user)
    """Personalised ranked startup feed.

    With fewer than 5 behavioural events the response is flagged `cold_start`
    and ranking falls back entirely to stated preferences --- the report's
    structured-onboarding answer to the cold-start problem.
    """
    inv = (
        db.query(Investor)
        .options(selectinload(Investor.preference))
        .filter(Investor.investor_id == investor_id)
        .first()
    )
    if not inv:
        raise HTTPException(404, "Investor not found")

    matches = build_feed(
        db, inv, limit=limit, exclude_seen=exclude_seen, min_composite=min_composite
    )
    return [
        {
            "startup": _summary(m["startup"]),
            "match_score": m["match_score"],
            "preference_score": m["preference_score"],
            "behavioral_score": m["behavioral_score"],
            "network_score": m["network_score"],
            "quality_score": m["quality_score"],
            "reasons": m["reasons"],
            "cold_start": m["cold_start"],
        }
        for m in matches
    ]


@router.get("/{investor_id}/activity")
def activity(investor_id: str, limit: int = 40, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    owns_investor(investor_id, user)
    from app.models import Startup

    events = (
        db.query(BehavioralEvent)
        .filter(BehavioralEvent.investor_id == investor_id)
        .order_by(BehavioralEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    ids = {e.startup_id for e in events if e.startup_id}
    names = (
        {
            s.startup_id: s.legal_name
            for s in db.query(Startup).filter(Startup.startup_id.in_(ids)).all()
        }
        if ids
        else {}
    )
    return [
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "startup_id": e.startup_id,
            "startup_name": names.get(e.startup_id),
            "event_value": e.event_value,
            "occurred_at": e.occurred_at,
        }
        for e in events
    ]


# --------------------------------------------------------------------------
# Behavioural event ingest --- the Kafka-shaped write path
# --------------------------------------------------------------------------

events_router = APIRouter(prefix="/api/events", tags=["events"])


@events_router.post("", status_code=202)
def track(payload: EventIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Ingest one behavioural event.

    In the report this is a Kafka produce so the write never blocks the
    frontend. At MVP volume we write straight through, but the endpoint keeps
    the fire-and-forget contract (202, no body) so a producer can be dropped in
    front without changing any caller.
    """
    owns_investor(payload.investor_id, user)

    db.add(
        BehavioralEvent(
            investor_id=payload.investor_id,
            startup_id=payload.startup_id,
            event_type=payload.event_type,
            event_value=payload.event_value,
        )
    )
    db.commit()
    return {"accepted": True}


@events_router.post("/batch", status_code=202)
def track_batch(payloads: list[EventIn], db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    for p in payloads[:200]:
        owns_investor(p.investor_id, user)
        db.add(
            BehavioralEvent(
                investor_id=p.investor_id,
                startup_id=p.startup_id,
                event_type=p.event_type,
                event_value=p.event_value,
            )
        )
    db.commit()
    return {"accepted": len(payloads[:200])}
