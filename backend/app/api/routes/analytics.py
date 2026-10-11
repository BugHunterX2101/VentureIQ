"""Dashboard aggregates, model transparency, and the simulated marketplace."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import ARTIFACTS
from app.api.deps import current_user
from app.core.database import get_db
from app.models import (
    AuditLog,
    BehavioralEvent,
    EnrichmentRecord,
    FraudSignal,
    FundingRound,
    Investor,
    Listing,
    User,
    Score,
    Startup,
    StartupFinancials,
)

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/stats")
def platform_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Startup.startup_id)).scalar() or 0
    scored = db.query(func.count(func.distinct(Score.startup_id))).scalar() or 0
    verified = (
        db.query(func.count(Startup.startup_id)).filter(Startup.verified.is_(True)).scalar() or 0
    )
    investors = db.query(func.count(Investor.investor_id)).scalar() or 0
    events = db.query(func.count(BehavioralEvent.event_id)).scalar() or 0
    enrichments = db.query(func.count(EnrichmentRecord.enrichment_id)).scalar() or 0
    high_risk = (
        db.query(func.count(func.distinct(FraudSignal.startup_id)))
        .filter(FraudSignal.severity.in_(["high", "medium"]))
        .scalar()
        or 0
    )
    avg_composite = db.query(func.avg(Score.composite_score)).scalar()
    total_funding = db.query(func.sum(StartupFinancials.total_funding_usd)).scalar()

    return {
        "startups": total,
        "scored": scored,
        "verified": verified,
        "investors": investors,
        "behavioral_events": events,
        "enrichment_calls": enrichments,
        "flagged_startups": high_risk,
        "avg_composite_score": round(float(avg_composite), 1) if avg_composite else None,
        "total_tracked_funding_usd": float(total_funding) if total_funding else 0.0,
    }


@router.get("/stats/sectors")
def sector_breakdown(limit: int = Query(12, ge=1, le=40), db: Session = Depends(get_db)):
    rows = (
        db.query(
            Startup.sector,
            func.count(func.distinct(Startup.startup_id)).label("n"),
            func.avg(Score.composite_score).label("avg_score"),
            func.avg(Score.fraud_likelihood_score).label("avg_fraud"),
        )
        .join(Score, (Score.startup_id == Startup.startup_id) & Score.is_current.is_(True))
        .group_by(Startup.sector)
        .order_by(func.count(func.distinct(Startup.startup_id)).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "sector": r[0],
            "count": r[1],
            "avg_composite_score": round(float(r[2]), 1) if r[2] else None,
            "avg_fraud_score": round(float(r[3]), 1) if r[3] else None,
        }
        for r in rows
    ]


@router.get("/stats/stages")
def stage_breakdown(db: Session = Depends(get_db)):
    rows = (
        db.query(
            Startup.stage,
            func.count(func.distinct(Startup.startup_id)),
            func.avg(Score.composite_score),
        )
        .join(Score, (Score.startup_id == Startup.startup_id) & Score.is_current.is_(True))
        .group_by(Startup.stage)
        .all()
    )
    order = ["idea", "seed", "series_a", "series_b_plus", "growth"]
    out = [
        {
            "stage": r[0],
            "count": r[1],
            "avg_composite_score": round(float(r[2]), 1) if r[2] else None,
        }
        for r in rows
    ]
    out.sort(key=lambda x: order.index(x["stage"]) if x["stage"] in order else 99)
    return out


@router.get("/stats/score-distribution")
def score_distribution(db: Session = Depends(get_db)):
    """Histogram of composite scores in 10-point buckets."""
    scores = [
        s[0]
        for s in db.query(Score.composite_score)
        .filter(Score.composite_score.isnot(None))
        .all()
    ]
    buckets = [0] * 10
    for v in scores:
        buckets[min(int(v // 10), 9)] += 1
    return [
        {"bucket": f"{i * 10}-{i * 10 + 9}", "lower": i * 10, "count": c}
        for i, c in enumerate(buckets)
    ]


@router.get("/stats/funding-timeline")
def funding_timeline(db: Session = Depends(get_db)):
    """Real funding rounds per year from the seeded Indian dataset."""
    rows = db.query(FundingRound.announced_date, FundingRound.amount_usd).all()
    by_year: dict[int, dict[str, float]] = {}
    for d, amt in rows:
        if not d:
            continue
        y = d.year
        if y < 2010 or y > 2026:
            continue
        b = by_year.setdefault(y, {"year": y, "rounds": 0, "total_usd": 0.0})
        b["rounds"] += 1
        if amt:
            b["total_usd"] += amt
    return sorted(by_year.values(), key=lambda x: x["year"])


@router.get("/stats/cities")
def city_breakdown(limit: int = 10, db: Session = Depends(get_db)):
    rows = (
        db.query(Startup.hq_city, func.count(Startup.startup_id))
        .filter(Startup.hq_city.isnot(None), Startup.hq_city != "")
        .group_by(Startup.hq_city)
        .order_by(func.count(Startup.startup_id).desc())
        .limit(limit)
        .all()
    )
    return [{"city": r[0], "count": r[1]} for r in rows]


@router.get("/stats/constellation")
def constellation(limit: int = Query(1800, ge=100, le=10000), db: Session = Depends(get_db)):
    """Compact per-company points for the landing page's 3D constellation.

    Every point is a real scored startup. Column arrays keep the payload small
    enough to plot thousands of companies without paging the full list API.
    Sectors outside the main taxonomy (fewer than 20 companies) fold into
    "Other" so the scene has a legible number of arms.
    """
    rows = (
        db.query(
            Startup.startup_id,
            Startup.legal_name,
            Startup.sector,
            Startup.verified,
            Score.composite_score,
            Score.fraud_likelihood_score,
        )
        .join(Score, (Score.startup_id == Startup.startup_id) & Score.is_current.is_(True))
        .order_by(Score.composite_score.desc())
        .all()
    )
    # Even stride across the whole score distribution, so the scene shows the
    # real spread of the corpus rather than only its best companies.
    step = max(1, len(rows) // limit)
    rows = rows[::step][:limit]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.sector] = counts.get(r.sector, 0) + 1
    main = sorted((s for s, n in counts.items() if n >= 20), key=lambda s: -counts[s])
    sectors = main + (["Other"] if any(counts[s] < 20 for s in counts) else [])
    index = {s: i for i, s in enumerate(sectors)}
    other = index.get("Other", 0)

    return {
        "sectors": sectors,
        "count": len(rows),
        "id": [r.startup_id for r in rows],
        "name": [r.legal_name for r in rows],
        "sector": [index.get(r.sector, other) for r in rows],
        "score": [round(r.composite_score, 1) for r in rows],
        "fraud": [round(r.fraud_likelihood_score, 1) for r in rows],
        "verified": [bool(r.verified) for r in rows],
    }


@router.get("/model/metrics")
def model_metrics():
    """Expose the trained model's real held-out metrics.

    Surfaced in the UI on purpose: the report's whole argument is that investors
    should not take a score on faith, and that has to apply to our own model too.
    """
    path = ARTIFACTS / "growth_metrics.json"
    if not path.exists():
        raise HTTPException(404, "Model not trained yet — run python -m app.ml.train")
    payload = json.loads(path.read_text())

    # The survival model is a separate model on a separate corpus, so it is
    # reported separately rather than folded into the growth numbers.
    survival_path = ARTIFACTS / "survival_metrics.json"
    if survival_path.exists():
        payload["survival"] = json.loads(survival_path.read_text())
    return payload


@router.get("/alerts")
def alerts(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """Real-time fraud/risk alert feed for the investor dashboard."""
    rows = (
        db.query(FraudSignal, Startup)
        .join(Startup, Startup.startup_id == FraudSignal.startup_id)
        .filter(FraudSignal.severity.in_(["high", "medium"]))
        .order_by(FraudSignal.run_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "signal_id": sig.signal_id,
            "startup_id": s.startup_id,
            "startup_name": s.legal_name,
            "sector": s.sector,
            "detector": sig.detector,
            "severity": sig.severity,
            "anomaly_score": sig.anomaly_score,
            "explanation": sig.explanation,
            "flagged_fields": sig.flagged_fields,
            "reviewed_by_human": sig.reviewed_by_human,
            "run_at": sig.run_at,
        }
        for sig, s in rows
    ]


@router.get("/audit")
def audit_log(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "log_id": r.log_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "timestamp": r.timestamp,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------
# Marketplace --- SIMULATED. No real money, no real equity transfer.
# --------------------------------------------------------------------------

market = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

DISCLAIMER = (
    "SIMULATED. Escrow, settlement and equity transfer are SEBI/RBI-regulated "
    "activities requiring licences this project does not hold. No real funds move. "
    "See docs/BUILD_PLAN.md Problem 1."
)


def _fair_value(db: Session, s: Startup) -> float | None:
    """Revenue multiple anchored on the peer cohort, adjusted by composite score.

    Deliberately simple and legible --- a valuation number that cannot be
    explained is worse than no number.
    """
    fin = s.latest_financials
    score = s.latest_score
    if not fin:
        return None

    revenue = fin.revenue or 0
    funding = fin.total_funding_usd or 0
    stage_multiple = {
        "idea": 3.0, "seed": 8.0, "series_a": 6.5,
        "series_b_plus": 5.0, "growth": 4.0,
    }.get(s.stage, 5.0)

    if revenue > 0:
        base = revenue * stage_multiple
    elif funding > 0:
        base = funding * 2.5
    else:
        return None

    if score:
        base *= 0.6 + (score.composite_score / 100.0) * 0.8
    return round(base, 2)


@market.get("/listings")
def listings(db: Session = Depends(get_db), limit: int = 30):
    rows = (
        db.query(Listing, Startup)
        .join(Startup, Startup.startup_id == Listing.startup_id)
        .order_by(Listing.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "disclaimer": DISCLAIMER,
        "items": [
            {
                "listing_id": ls.listing_id,
                "startup_id": s.startup_id,
                "startup_name": s.legal_name,
                "sector": s.sector,
                "stage": s.stage,
                "ask_amount": ls.ask_amount,
                "equity_offered_pct": ls.equity_offered_pct,
                "fair_value_estimate": ls.fair_value_estimate,
                "status": ls.status,
                "composite_score": s.latest_score.composite_score if s.latest_score else None,
                "simulated": True,
            }
            for ls, s in rows
        ],
    }


@market.post("/listings", status_code=201)
def create_listing(
    startup_id: str,
    ask_amount: float = Query(..., gt=0),
    equity_offered_pct: float = Query(..., gt=0, le=100),
    rofr_days: int = Query(7, ge=0, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    s = db.query(Startup).filter(Startup.startup_id == startup_id).first()
    if not s:
        raise HTTPException(404, "Startup not found")
    # Only the founder who registered a company may list it.
    if s.owner_user_id and s.owner_user_id != user.user_id:
        raise HTTPException(403, "Only the founder who registered this company can list it")
    if not s.owner_user_id and user.role != "founder":
        raise HTTPException(403, "Only a founder account can create a listing")

    # One live listing per company. Two open listings would offer the same
    # equity twice over, and an investor reading the marketplace could not tell
    # which one they were bidding into.
    live = (
        db.query(Listing)
        .filter(Listing.startup_id == startup_id, Listing.status.in_(["open", "under_offer"]))
        .first()
    )
    if live:
        raise HTTPException(
            409,
            "This company is already listed. Close or settle the existing listing "
            "before creating another.",
        )

    score = s.latest_score
    # Compliance-as-code: a company flagged for fraud cannot be listed.
    if score and score.fraud_likelihood_score > 60:
        raise HTTPException(
            422,
            "Blocked by compliance: elevated fraud signals. Human review required "
            "before this startup can be listed.",
        )
    if not s.verified:
        raise HTTPException(
            422, "Blocked by compliance: startup registration is not verified (run enrichment first)"
        )

    ls = Listing(
        startup_id=startup_id,
        ask_amount=ask_amount,
        equity_offered_pct=equity_offered_pct,
        fair_value_estimate=_fair_value(db, s),
        simulated=True,
        created_by_user_id=user.user_id,
        rofr_days=rofr_days,
    )
    db.add(ls)
    db.add(
        AuditLog(
            actor_id=user.user_id,
            action="listing.created",
            entity_type="listing",
            entity_id=ls.listing_id,
            detail={"startup_id": startup_id, "ask": ask_amount, "simulated": True},
        )
    )
    db.commit()
    db.refresh(ls)
    return {
        "listing_id": ls.listing_id,
        "fair_value_estimate": ls.fair_value_estimate,
        "implied_valuation": round(ask_amount / (equity_offered_pct / 100), 2),
        "disclaimer": DISCLAIMER,
    }


@market.get("/valuation/{startup_id}")
def valuation(startup_id: str, db: Session = Depends(get_db)):
    s = db.query(Startup).filter(Startup.startup_id == startup_id).first()
    if not s:
        raise HTTPException(404, "Startup not found")
    fin = s.latest_financials
    fv = _fair_value(db, s)
    return {
        "startup_id": startup_id,
        "fair_value_estimate": fv,
        "basis": {
            "revenue": fin.revenue if fin else None,
            "total_funding_usd": fin.total_funding_usd if fin else None,
            "stage": s.stage,
            "composite_score": s.latest_score.composite_score if s.latest_score else None,
        },
        "method": (
            "Stage-appropriate revenue multiple, adjusted by the AI composite score. "
            "Falls back to a funding multiple for pre-revenue companies."
        ),
        "disclaimer": DISCLAIMER,
    }
