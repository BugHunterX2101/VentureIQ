"""Startup pipeline endpoints (report Layer 2 + Layer 3 output)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, selectinload

from app.api.deps import optional_user
from app.core.database import get_db
from app.enrichment.agent import attach_mock_founders, enrich_startup
from app.ml import rag
from app.ml.scoring import compute_scores
from app.models import AuditLog, Founder, Score, Startup, StartupFinancials, User
from app.schemas.dto import (
    BenchmarkOut,
    PaginatedStartups,
    StartupDetail,
    StartupIn,
    StartupSummary,
)

router = APIRouter(prefix="/api/startups", tags=["startups"])


def _summary(s: Startup) -> dict[str, Any]:
    score = s.latest_score
    fin = s.latest_financials
    return {
        "startup_id": s.startup_id,
        "legal_name": s.legal_name,
        "logo_url": s.logo_url,
        "stage": s.stage,
        "sector": s.sector,
        "sub_vertical": s.sub_vertical,
        "hq_city": s.hq_city,
        "one_liner": s.one_liner,
        "employee_count": s.employee_count,
        "status": s.status,
        "verified": s.verified,
        "source": s.source,
        "composite_score": score.composite_score if score else None,
        "growth_potential_score": score.growth_potential_score if score else None,
        "risk_level_score": score.risk_level_score if score else None,
        "fraud_likelihood_score": score.fraud_likelihood_score if score else None,
        "founder_credibility_score": score.founder_credibility_score if score else None,
        "total_funding_usd": fin.total_funding_usd if fin else None,
    }


def _cohort_stats(db: Session, s: Startup) -> dict[str, int]:
    n = (
        db.query(func.count(Startup.startup_id))
        .filter(Startup.sector == s.sector, Startup.stage == s.stage)
        .scalar()
        or 0
    )
    return {"cohort_size": n, "sector_density": n}


@router.get("", response_model=PaginatedStartups)
def list_startups(
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="Free-text search on name / description"),
    sector: str | None = None,
    stage: str | None = None,
    city: str | None = None,
    min_score: float | None = Query(None, ge=0, le=100),
    max_fraud: float | None = Query(None, ge=0, le=100),
    verified_only: bool = False,
    sort: str = Query("composite_score", pattern="^(composite_score|growth|risk|founder|name|recent)$"),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    query = db.query(Startup).options(
        selectinload(Startup.scores), selectinload(Startup.financials)
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Startup.legal_name.ilike(like),
                Startup.one_liner.ilike(like),
                Startup.long_description.ilike(like),
                Startup.sector.ilike(like),
            )
        )
    if sector:
        query = query.filter(Startup.sector == sector)
    if stage:
        query = query.filter(Startup.stage == stage)
    if city:
        query = query.filter(Startup.hq_city.ilike(f"%{city}%"))
    if verified_only:
        query = query.filter(Startup.verified.is_(True))

    if min_score is not None or max_fraud is not None or sort in {
        "composite_score", "growth", "risk", "founder"
    }:
        query = query.join(
            Score, (Score.startup_id == Startup.startup_id) & Score.is_current.is_(True)
        )
        if min_score is not None:
            query = query.filter(Score.composite_score >= min_score)
        if max_fraud is not None:
            query = query.filter(Score.fraud_likelihood_score <= max_fraud)

    sort_col = {
        "composite_score": Score.composite_score.desc(),
        "growth": Score.growth_potential_score.desc(),
        "risk": Score.risk_level_score.desc(),
        "founder": Score.founder_credibility_score.desc(),
        "name": Startup.legal_name.asc(),
        "recent": Startup.created_at.desc(),
    }[sort]
    if q:
        # Someone typing a company name wants that company, not whichever
        # high-scoring company happens to mention it in its description. Rank
        # by how well the *name* matches first, and only then by the chosen
        # sort. Without this, "Ola" returns a solar firm called Oolu, because
        # "solar" contains the query and scores higher.
        needle = q.strip().lower()
        name = func.lower(Startup.legal_name)
        query = query.order_by(
            case(
                (name == needle, 0),
                (name.like(f"{needle}%"), 1),
                (name.like(f"%{needle}%"), 2),
                else_=3,
            ),
            sort_col,
        )
    else:
        query = query.order_by(sort_col)

    total = query.distinct().count()
    rows = query.distinct().offset(offset).limit(limit).all()
    return {
        "items": [_summary(s) for s in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/sectors")
def list_sectors(db: Session = Depends(get_db)):
    rows = (
        db.query(Startup.sector, func.count(Startup.startup_id))
        .group_by(Startup.sector)
        .order_by(func.count(Startup.startup_id).desc())
        .all()
    )
    return [{"sector": r[0], "count": r[1]} for r in rows]


@router.get("/{startup_id}", response_model=StartupDetail)
def get_startup(
    startup_id: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
):
    s = (
        db.query(Startup)
        .options(
            selectinload(Startup.scores),
            selectinload(Startup.financials),
            selectinload(Startup.founders),
            selectinload(Startup.fraud_signals),
            selectinload(Startup.enrichments),
        )
        .filter(Startup.startup_id == startup_id)
        .first()
    )
    if not s:
        raise HTTPException(404, "Startup not found")

    payload = _summary(s)
    payload.update(
        {
            "long_description": s.long_description,
            "website": s.website,
            "hq_state": s.hq_state,
            "founded_date": s.founded_date,
            "yc_batch": s.yc_batch,
            "logo_source": s.logo_source,
            "company_linkedin_url": s.linkedin_url,
            "company_twitter_url": s.twitter_url,
            "company_github_org": s.github_org,
            # Whether the viewer owns this company, so the page can offer the
            # founder's actions. The owner's identity itself stays private.
            "owned_by_me": bool(user and s.owner_user_id and s.owner_user_id == user.user_id),
            "cin": s.cin,
            "gstin": s.gstin,
            "created_at": s.created_at,
            # CEO first, then stable by name: the page should not reorder
            # the same team between refreshes.
            "founders": sorted(
                s.founders, key=lambda f: ("CEO" not in (f.role or ""), f.name or "")
            ),
            "financials": s.latest_financials,
            "score": s.latest_score,
            "fraud_signals": sorted(s.fraud_signals, key=lambda f: f.run_at, reverse=True)[:10],
            "enrichments": sorted(s.enrichments, key=lambda e: e.retrieved_at, reverse=True)[:12],
        }
    )
    return payload


@router.post("", response_model=StartupDetail, status_code=201)
def create_startup(
    payload: StartupIn,
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
):
    """Register a startup.

    Pydantic has already enforced the stage-conditional rules (an idea-stage
    company is not asked for burn rate; a seed-stage one must supply it) --- this
    is the server half of the two-layer validation the report specifies.

    A signed-in founder owns what they submit here, exactly as they would
    through the agent. Without that the company never reaches "My companies",
    cannot be listed, and has nobody who can accept a mentorship offer.
    Anonymous submission still works; the company is simply unclaimed.
    """
    s = Startup(
        legal_name=payload.legal_name,
        stage=payload.stage,
        sector=payload.sector,
        sub_vertical=payload.sub_vertical,
        founded_date=payload.founded_date,
        hq_city=payload.hq_city,
        hq_state=payload.hq_state,
        website=payload.website,
        cin=payload.cin,
        gstin=payload.gstin,
        one_liner=payload.one_liner,
        long_description=payload.long_description,
        employee_count=payload.employee_count,
        source="registration",
        owner_user_id=user.user_id if user and user.role == "founder" else None,
    )
    db.add(s)
    db.flush()

    for f in payload.founders:
        db.add(
            Founder(
                startup_id=s.startup_id,
                name=f.name,
                role=f.role,
                linkedin_url=f.linkedin_url,
                github_username=f.github_username,
            )
        )

    if payload.financials:
        db.add(StartupFinancials(startup_id=s.startup_id, **payload.financials.model_dump()))

    db.add(
        AuditLog(
            action="startup.created",
            entity_type="startup",
            entity_id=s.startup_id,
            detail={"legal_name": s.legal_name, "stage": s.stage},
        )
    )
    db.commit()
    db.refresh(s)

    compute_scores(db, s, cohort_stats=_cohort_stats(db, s))
    db.commit()
    rag.INDEX.built = False  # corpus changed; rebuild lazily on next retrieval
    # Pass the caller through: FastAPI only resolves Depends() at the route
    # boundary, so calling this as a plain function leaves it unresolved.
    return get_startup(s.startup_id, db, user)


@router.post("/{startup_id}/score")
def rescore(startup_id: str, db: Session = Depends(get_db)):
    s = db.query(Startup).filter(Startup.startup_id == startup_id).first()
    if not s:
        raise HTTPException(404, "Startup not found")
    score = compute_scores(db, s, cohort_stats=_cohort_stats(db, s))
    db.add(
        AuditLog(
            action="startup.rescored",
            entity_type="startup",
            entity_id=startup_id,
            detail={"composite": score.composite_score},
        )
    )
    db.commit()
    return {
        "startup_id": startup_id,
        "composite_score": score.composite_score,
        "growth_potential_score": score.growth_potential_score,
        "risk_level_score": score.risk_level_score,
        "fraud_likelihood_score": score.fraud_likelihood_score,
        "founder_credibility_score": score.founder_credibility_score,
        "rationale": score.rationale,
        "shap_top_features": score.shap_top_features,
        "confidence": score.confidence,
        "model_version": score.model_version,
    }


@router.post("/{startup_id}/enrich")
async def enrich(startup_id: str, force: bool = False, db: Session = Depends(get_db)):
    """Run the agentic enrichment loop and rescore against the new evidence."""
    s = (
        db.query(Startup)
        .options(selectinload(Startup.founders), selectinload(Startup.financials))
        .filter(Startup.startup_id == startup_id)
        .first()
    )
    if not s:
        raise HTTPException(404, "Startup not found")

    if not s.founders:
        attach_mock_founders(db, s)
        db.commit()
        db.refresh(s)

    trace = await enrich_startup(db, s, force=force)
    db.refresh(s)
    score = compute_scores(db, s, cohort_stats=_cohort_stats(db, s))
    db.add(
        AuditLog(
            action="startup.enriched",
            entity_type="startup",
            entity_id=startup_id,
            detail={"sources": trace["executed"]},
        )
    )
    db.commit()

    return {
        "trace": trace,
        "score": {
            "composite_score": score.composite_score,
            "growth_potential_score": score.growth_potential_score,
            "risk_level_score": score.risk_level_score,
            "fraud_likelihood_score": score.fraud_likelihood_score,
            "founder_credibility_score": score.founder_credibility_score,
            "rationale": score.rationale,
        },
    }


@router.get("/{startup_id}/benchmark", response_model=BenchmarkOut)
def get_benchmark(startup_id: str, db: Session = Depends(get_db)):
    """RAG peer comparison --- top-k similar startups, same stage and sector."""
    s = db.query(Startup).filter(Startup.startup_id == startup_id).first()
    if not s:
        raise HTTPException(404, "Startup not found")
    return rag.benchmark(db, s)


@router.get("/{startup_id}/competitors")
def competitors(startup_id: str, k: int = Query(8, ge=1, le=20), db: Session = Depends(get_db)):
    """The company set side by side with its nearest comparable companies.

    The peer list is the same retrieval the benchmark uses; what this adds is
    the numbers lined up in one shape, plus the median of the set, so a reader
    can see where the company sits rather than reading eight profiles. Medians,
    not means: one company that raised $2bn would otherwise drag the row.
    """
    s = db.query(Startup).filter(Startup.startup_id == startup_id).first()
    if not s:
        raise HTTPException(404, "Startup not found")

    pairs = rag.INDEX.retrieve(db, s, k=k, strict=False)
    similarity = {sid: score for sid, score in pairs}
    rows = (
        db.query(Startup)
        .options(selectinload(Startup.scores), selectinload(Startup.financials))
        .filter(Startup.startup_id.in_(list(similarity)))
        .all()
        if similarity
        else []
    )
    rows.sort(key=lambda r: -similarity.get(r.startup_id, 0.0))

    def row(x: Startup, sim: float | None) -> dict[str, Any]:
        fin = x.latest_financials
        score = x.latest_score
        return {
            **_summary(x),
            "similarity": round(sim, 4) if sim is not None else None,
            "founded_year": x.founded_date.year if x.founded_date else None,
            "yc_batch": x.yc_batch,
            "revenue": fin.revenue if fin else None,
            "runway_months": fin.runway_months if fin else None,
            "growth_potential_score": score.growth_potential_score if score else None,
            "risk_level_score": score.risk_level_score if score else None,
        }

    peers = [row(x, similarity.get(x.startup_id)) for x in rows]

    def median(key: str) -> float | None:
        values = sorted(p[key] for p in peers if p.get(key) is not None)
        if not values:
            return None
        mid = len(values) // 2
        return float(values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2)

    return {
        "subject": row(s, None),
        "peers": peers,
        "median": {k2: median(k2) for k2 in (
            "total_funding_usd", "employee_count", "composite_score",
            "growth_potential_score", "risk_level_score", "revenue",
        )},
        "basis": (
            f"Nearest {len(peers)} companies by description, stage and sector, "
            "from the 9,287-company corpus."
        ),
    }


@router.get("/{startup_id}/similar", response_model=list[StartupSummary])
def similar(startup_id: str, k: int = Query(6, ge=1, le=20), db: Session = Depends(get_db)):
    s = db.query(Startup).filter(Startup.startup_id == startup_id).first()
    if not s:
        raise HTTPException(404, "Startup not found")
    peers = rag.INDEX.retrieve(db, s, k=k, strict=False)
    ids = [p[0] for p in peers]
    if not ids:
        return []
    rows = db.query(Startup).filter(Startup.startup_id.in_(ids)).all()
    order = {sid: i for i, sid in enumerate(ids)}
    rows.sort(key=lambda r: order.get(r.startup_id, 999))
    return [_summary(r) for r in rows]
