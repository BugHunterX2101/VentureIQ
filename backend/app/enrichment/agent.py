"""The agentic enrichment loop.

What makes this agentic rather than a fixed pipeline (report section 8.1.3):
the planner inspects what is *missing or unverified* on a given startup and
decides which sources to query and in what order. A company with no GitHub
handle never gets a GitHub call; a company whose MCA21 check already came back
clean does not get re-queried while the cache is warm; a revenue claim that
disagrees with GSTN escalates into follow-up checks that would not otherwise run.

Retry policy follows the report: 5 retries, exponential backoff, fall back to a
cached result up to `enrichment_cache_days` old.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.enrichment.adapters import ADAPTERS
from app.ml.features import utcnow
from app.models import EnrichmentRecord, Founder, Startup


def plan(startup: Startup, cached: set[str]) -> list[str]:
    """Decide which sources to call, in priority order.

    Ordering matters: identity first (does this company legally exist?), then
    the financial cross-check, then the softer founder/domain signals. If the
    company does not verify as registered there is little point spending calls
    on endorsement counts.
    """
    steps: list[str] = []

    if not startup.cin or not startup.verified:
        steps.append("mca21")

    fin = startup.latest_financials
    if fin and fin.revenue:
        steps.append("gstn")

    if any(f.github_username for f in startup.founders):
        steps.append("github")

    if startup.founders and any(
        f.prior_exits is None or f.domain_experience_years is None for f in startup.founders
    ):
        steps.append("linkedin")

    if startup.website:
        steps.append("whois")

    # Skip anything already cached and still fresh.
    return [s for s in steps if s not in cached]


def _cached_sources(db: Session, startup_id: str) -> set[str]:
    cutoff = utcnow().replace(tzinfo=None) - timedelta(days=settings.enrichment_cache_days)
    rows = (
        db.query(EnrichmentRecord.source)
        .filter(
            EnrichmentRecord.startup_id == startup_id,
            EnrichmentRecord.status == "success",
            EnrichmentRecord.retrieved_at >= cutoff,
        )
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


async def _call_with_retries(adapter: Any, startup: Startup) -> tuple[dict | None, int, str | None]:
    """Exponential backoff, capped at settings.enrichment_max_retries."""
    last_error: str | None = None
    for attempt in range(settings.enrichment_max_retries):
        try:
            payload = await adapter.fetch(startup)
            return payload, attempt, None
        except Exception as exc:  # noqa: BLE001 - adapters raise anything
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < settings.enrichment_max_retries - 1:
                await asyncio.sleep(min(2**attempt * 0.25, 4.0))
    return None, settings.enrichment_max_retries, last_error


def _apply_to_founders(db: Session, startup: Startup, source: str, payload: dict) -> None:
    """Write enrichment results onto the founder rows the scorer reads."""
    people = payload.get("founders") or {}

    if source == "linkedin":
        for founder in startup.founders:
            data = people.get(founder.name)
            if not data or data.get("error"):
                continue
            if data.get("_provenance") or data.get("positions") is not None:
                # Real profile: a profile has no structured "exit" field, so
                # prior exits stay unknown unless the founder wrote it up.
                founder.prior_exits = data.get("self_reported_exits")
                founder.domain_experience_years = data.get("domain_experience_years")
                founder.linkedin_endorsement_count = data.get("connections")
                founder.linkedin_employment_history = {
                    "roles": data.get("positions", []),
                    "education": data.get("education", []),
                    "headline": data.get("headline"),
                    "source": "rapidapi",
                }
            else:
                founder.prior_exits = data.get("prior_exits")
                founder.domain_experience_years = data.get("domain_experience_years")
                founder.linkedin_endorsement_count = data.get("endorsement_count")
                founder.linkedin_employment_history = {"roles": data.get("employment_history", [])}

    elif source == "github":
        for founder in startup.founders:
            data = people.get(founder.github_username or "")
            if not data or data.get("error"):
                continue
            founder.github_followers = data.get("followers")
            founder.github_contributor_count = data.get("public_repos")
            # Recently-pushed repos is our proxy for 90-day commit activity;
            # the exact commit count needs per-repo pagination we skip here.
            founder.github_commit_count_90d = data.get("recently_pushed_repos", 0) * 12

    db.flush()


def _apply_to_startup(db: Session, startup: Startup, source: str, payload: dict) -> None:
    mocked = bool(payload.get("_mock"))
    if source == "mca21":
        if payload.get("registration_verified") is None:
            pass  # nothing to check against; leave the flag as it was
        elif payload.get("registration_verified"):
            # A mocked registry invents identifiers; never write those onto a profile.
            if not mocked:
                startup.cin = payload.get("cin") or startup.cin
            startup.verified = True
        else:
            startup.verified = False
    elif source == "gstn":
        if not mocked:
            startup.gstin = payload.get("gstin") or startup.gstin
        fin = startup.latest_financials
        if fin and payload.get("gst_reported_annual_revenue") is not None:
            fin.gst_reported_revenue = payload["gst_reported_annual_revenue"]
    db.flush()


async def enrich_startup(db: Session, startup: Startup, force: bool = False) -> dict[str, Any]:
    """Run the agentic loop for one startup. Returns a trace of what it did."""
    cached = set() if force else _cached_sources(db, startup.startup_id)
    steps = plan(startup, cached)

    trace: dict[str, Any] = {
        "startup_id": startup.startup_id,
        "planned": steps,
        "skipped_cached": sorted(cached),
        "executed": [],
        "escalations": [],
    }

    for source in steps:
        adapter = ADAPTERS.get(source)
        if not adapter or not adapter.applicable(startup):
            trace["executed"].append({"source": source, "status": "skipped_not_applicable"})
            continue

        payload, retries, error = await _call_with_retries(adapter, startup)
        status = "success" if payload is not None else "failed"

        db.add(
            EnrichmentRecord(
                startup_id=startup.startup_id,
                source=source,
                is_mock=bool(payload.get("_mock", adapter.is_mock)) if payload else adapter.is_mock,
                query_params={"legal_name": startup.legal_name},
                raw_response=payload,
                status=status,
                error=error,
                retry_count=retries,
            )
        )

        if payload is not None:
            _apply_to_startup(db, startup, source, payload)
            _apply_to_founders(db, startup, source, payload)

            # --- agentic escalation: a bad GSTN result triggers extra checks ---
            if source == "gstn" and payload.get("exceeds_threshold"):
                trace["escalations"].append(
                    {
                        "trigger": "gstn_revenue_deviation",
                        "detail": (
                            f"Revenue deviation {payload.get('deviation_fraction'):.1%} "
                            f"exceeds the {settings.deviation_threshold:.0%} threshold"
                        ),
                        "action": "queued mca21 re-verification and flagged for human review",
                    }
                )
                if "mca21" not in steps and "mca21" not in [
                    e.get("source") for e in trace["executed"]
                ]:
                    steps.append("mca21")

            if source == "mca21" and not payload.get("registration_verified"):
                trace["escalations"].append(
                    {
                        "trigger": "mca21_not_registered",
                        "detail": "No matching MCA registration found for this company name",
                        "action": "startup marked unverified; blocked from marketplace listing",
                    }
                )

        trace["executed"].append(
            {
                "source": source,
                "status": status,
                "is_mock": adapter.is_mock,
                "retries": retries,
                "error": error,
            }
        )

    db.commit()
    return trace


def attach_mock_founders(db: Session, startup: Startup) -> list[Founder]:
    """Seeded startups have no founder rows (the CSVs mostly lack names).

    Creates plausible founder placeholders so the founder-credibility path is
    exercisable end-to-end in the demo. Real registrations supply real founders
    through the form.
    """
    from app.enrichment.adapters import _seed_for

    if startup.founders:
        return list(startup.founders)

    rng = _seed_for("founders", startup.legal_name)
    first = ["Aarav", "Vivaan", "Ananya", "Diya", "Rohan", "Ishaan", "Kavya",
             "Meera", "Arjun", "Priya", "Karthik", "Sneha", "Rahul", "Neha"]
    last = ["Sharma", "Verma", "Iyer", "Reddy", "Nair", "Gupta", "Mehta",
            "Rao", "Kulkarni", "Bose", "Chopra", "Malhotra"]

    made: list[Founder] = []
    for i in range(rng.randint(1, 3)):
        name = f"{rng.choice(first)} {rng.choice(last)}"
        handle = name.lower().replace(" ", "") + str(rng.randint(10, 99))
        f = Founder(
            startup_id=startup.startup_id,
            name=name,
            role="Co-Founder & CEO" if i == 0 else rng.choice(["CTO", "COO", "Co-Founder"]),
            linkedin_url=(
                f"https://linkedin.com/in/{handle}" if rng.random() > 0.15 else None
            ),
            github_username=handle if rng.random() > 0.55 else None,
        )
        db.add(f)
        made.append(f)
    db.flush()
    return made
