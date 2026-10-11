"""Investor-startup matching (report section 8.2.3, Layer 4).

Four signals, blended:

  preference  structured onboarding --- ticket size, stage, sector, geography,
              risk tolerance. Load-bearing: it is the ONLY signal available for
              a brand-new investor, so the cold start depends entirely on it
              (docs/BUILD_PLAN.md Problem 4).
  behavioral  implicit feedback from the Kafka event stream. LightFM does
              collaborative filtering in the report; at MVP interaction volume
              CF has nothing to learn from, so this is item-item similarity over
              what the investor actually engaged with --- the same idea, honest
              about the data available.
  network     co-investment graph proximity (Neo4j in the report; networkx-shaped
              adjacency here per BUILD_PLAN Problem 5).
  quality     the AI Engine composite, so a great match on a bad company still
              ranks below a great match on a good one.

The report notes a rule worth keeping explicit: dismiss three fintech startups
in a row and you should stop being shown a fourth. `_dismissal_penalty` does it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models import BehavioralEvent, FundingRound, Investor, Score, Startup

WEIGHTS = {"preference": 0.40, "behavioral": 0.25, "network": 0.15, "quality": 0.20}

# Implicit-feedback strengths. Dismissal is negative on purpose.
EVENT_WEIGHTS = {
    "view": 0.15,
    "time_spent": 0.25,
    "document_view": 0.5,
    "save": 1.0,
    "interest_expressed": 1.5,
    "dismiss": -1.2,
}

STAGE_ORDER = ["idea", "seed", "series_a", "series_b_plus", "growth"]


def _preference_score(inv: Investor, s: Startup, fin_funding: float | None) -> tuple[float, list[str]]:
    pref = inv.preference
    if not pref:
        return 50.0, ["No stated preferences — showing broad results"]

    score, reasons = 0.0, []

    # Sector: the strongest single preference signal.
    sectors = pref.preferred_sectors or []
    if not sectors:
        score += 22
    elif s.sector in sectors:
        score += 40
        reasons.append(f"{s.sector} is a stated target sector")
    else:
        score += 4

    # Stage: exact match ideal, adjacent stage partial credit.
    stages = pref.stage_preference or []
    if not stages:
        score += 16
    elif s.stage in stages:
        score += 28
        reasons.append(f"{s.stage.replace('_', ' ').title()} stage matches mandate")
    else:
        try:
            gap = min(
                abs(STAGE_ORDER.index(s.stage) - STAGE_ORDER.index(p))
                for p in stages
                if p in STAGE_ORDER
            )
            score += max(0, 14 - gap * 6)
        except (ValueError, TypeError):
            score += 2

    # Geography.
    geos = pref.geographic_preference or []
    if not geos:
        score += 10
    elif any(
        g.lower() in ((s.hq_city or "") + " " + (s.hq_state or "")).lower() for g in geos
    ):
        score += 16
        reasons.append(f"Located in {s.hq_city}, a preferred geography")
    else:
        score += 2

    # Ticket size vs what the company has historically raised per round.
    lo, hi = pref.ticket_size_min, pref.ticket_size_max
    if lo is None and hi is None:
        score += 8
    elif fin_funding:
        if (lo or 0) <= fin_funding <= (hi or float("inf")):
            score += 16
            reasons.append(f"${fin_funding:,.0f} raised fits the ticket band")
        else:
            score += 4
    else:
        score += 6

    return min(score, 100.0), reasons


def _risk_alignment(inv: Investor, s: Startup) -> tuple[float, str | None]:
    """A low-risk-tolerance investor should not be fed fragile companies."""
    pref = inv.preference
    score_row = s.latest_score
    if not pref or not score_row:
        return 1.0, None

    safety = score_row.risk_level_score  # higher == safer
    tol = pref.risk_tolerance
    if tol == "low":
        if safety < 45:
            return 0.55, "Down-weighted: risk profile exceeds your low risk tolerance"
        return 1.08, None
    if tol == "high":
        if safety < 45:
            return 1.06, None
        return 1.0, None
    return 1.0, None


def _behavioral_profile(db: Session, investor_id: str) -> dict[str, Any]:
    """Build a taste profile from the event stream."""
    events = (
        db.query(BehavioralEvent)
        .filter(BehavioralEvent.investor_id == investor_id)
        .order_by(BehavioralEvent.occurred_at.desc())
        .limit(500)
        .all()
    )
    sector_affinity: dict[str, float] = defaultdict(float)
    stage_affinity: dict[str, float] = defaultdict(float)
    seen: set[str] = set()
    dismissed_sectors: Counter = Counter()
    recent_dismissals: list[str] = []

    startup_cache: dict[str, Startup] = {}
    ids = {e.startup_id for e in events if e.startup_id}
    if ids:
        for s in db.query(Startup).filter(Startup.startup_id.in_(ids)).all():
            startup_cache[s.startup_id] = s

    for e in events:
        if not e.startup_id:
            continue
        s = startup_cache.get(e.startup_id)
        if not s:
            continue
        seen.add(e.startup_id)
        w = EVENT_WEIGHTS.get(e.event_type, 0.1)
        if e.event_type == "time_spent":
            secs = (e.event_value or {}).get("seconds", 0)
            w = min(secs / 60.0, 3.0) * 0.25
        sector_affinity[s.sector] += w
        stage_affinity[s.stage] += w
        if e.event_type == "dismiss":
            dismissed_sectors[s.sector] += 1
            recent_dismissals.append(s.sector)

    return {
        "sector_affinity": dict(sector_affinity),
        "stage_affinity": dict(stage_affinity),
        "seen": seen,
        "dismissed_sectors": dismissed_sectors,
        "recent_dismissals": recent_dismissals[:12],
        "n_events": len(events),
    }


def _dismissal_penalty(profile: dict, sector: str) -> tuple[float, str | None]:
    """Three consecutive dismissals in a sector suppresses a fourth."""
    recent = profile["recent_dismissals"]
    streak = 0
    for sec in recent:
        if sec == sector:
            streak += 1
        else:
            break
    if streak >= 3:
        return 0.15, f"Suppressed: you dismissed {streak} {sector} startups in a row"
    if profile["dismissed_sectors"].get(sector, 0) >= 2:
        return 0.6, None
    return 1.0, None


def _network_scores(db: Session, investor: Investor) -> dict[str, float]:
    """Co-investment proximity.

    Builds sector-level affinity from which investors historically co-invested
    with firms the investor resembles. With no portfolio, this degrades to 0
    rather than erroring --- brand-new entities have no network position, which
    is exactly the limitation the report's cited paper (arXiv:2511.23364) calls out.
    """
    firm = (investor.firm_name or "").strip().lower()
    if not firm:
        return {}

    peer_sectors: Counter = Counter()
    rounds = db.query(FundingRound).limit(8000).all()
    startup_ids = {r.startup_id for r in rounds}
    sector_by_id = {
        s.startup_id: s.sector
        for s in db.query(Startup).filter(Startup.startup_id.in_(startup_ids)).all()
    } if startup_ids else {}

    co_investors: set[str] = set()
    for r in rounds:
        names = [n.lower() for n in (r.investor_names or [])]
        if any(firm in n or n in firm for n in names):
            co_investors.update(names)

    if not co_investors:
        return {}

    for r in rounds:
        names = [n.lower() for n in (r.investor_names or [])]
        if any(n in co_investors for n in names):
            sec = sector_by_id.get(r.startup_id)
            if sec:
                peer_sectors[sec] += 1

    if not peer_sectors:
        return {}
    top = max(peer_sectors.values())
    return {sec: cnt / top * 100 for sec, cnt in peer_sectors.items()}


def build_feed(
    db: Session,
    investor: Investor,
    limit: int = 20,
    exclude_seen: bool = False,
    min_composite: float | None = None,
) -> list[dict[str, Any]]:
    profile = _behavioral_profile(db, investor.investor_id)
    cold_start = profile["n_events"] < 5
    network = _network_scores(db, investor)

    sector_aff = profile["sector_affinity"]
    max_sector_aff = max(sector_aff.values()) if sector_aff else 0.0
    stage_aff = profile["stage_affinity"]
    max_stage_aff = max(stage_aff.values()) if stage_aff else 0.0

    # Only rank scored startups --- an unscored company has nothing to rank on.
    candidates = (
        db.query(Startup)
        .join(Score, (Score.startup_id == Startup.startup_id) & Score.is_current.is_(True))
        .distinct()
        .limit(4000)
        .all()
    )

    results: list[dict[str, Any]] = []
    for s in candidates:
        score_row = s.latest_score
        if not score_row:
            continue
        if min_composite is not None and score_row.composite_score < min_composite:
            continue
        if exclude_seen and s.startup_id in profile["seen"]:
            continue

        fin = s.latest_financials
        funding = fin.total_funding_usd if fin else None

        pref_score, reasons = _preference_score(investor, s, funding)

        behav = 0.0
        if max_sector_aff > 0:
            behav += (sector_aff.get(s.sector, 0.0) / max_sector_aff) * 60
        if max_stage_aff > 0:
            behav += (stage_aff.get(s.stage, 0.0) / max_stage_aff) * 40
        behav = max(0.0, min(behav, 100.0))
        if behav > 55:
            reasons.append(f"You engage heavily with {s.sector} startups")

        net = network.get(s.sector, 0.0)
        if net > 60:
            reasons.append(f"Your co-investors are active in {s.sector}")

        quality = score_row.composite_score

        blended = (
            WEIGHTS["preference"] * pref_score
            + WEIGHTS["behavioral"] * (behav if not cold_start else pref_score)
            + WEIGHTS["network"] * net
            + WEIGHTS["quality"] * quality
        )

        risk_mult, risk_reason = _risk_alignment(investor, s)
        if risk_reason:
            reasons.append(risk_reason)
        dismiss_mult, dismiss_reason = _dismissal_penalty(profile, s.sector)
        if dismiss_reason:
            reasons.append(dismiss_reason)

        blended *= risk_mult * dismiss_mult

        if score_row.fraud_likelihood_score > 60:
            blended *= 0.5
            reasons.append("Down-weighted: elevated fraud signals on this profile")

        if not reasons:
            reasons.append("Broad match on your stated mandate")

        results.append(
            {
                "startup": s,
                "match_score": round(min(blended, 100.0), 1),
                "preference_score": round(pref_score, 1),
                "behavioral_score": round(behav, 1),
                "network_score": round(net, 1),
                "quality_score": round(quality, 1),
                "reasons": reasons[:4],
                "cold_start": cold_start,
            }
        )

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit]
