"""One-shot bootstrap: build the DB, load real data, train, score, seed demo users.

    python scripts/bootstrap.py             # full run
    python scripts/bootstrap.py --fast      # India-only YC subset, quicker

Idempotent in the sense that it drops and rebuilds; safe to re-run.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    BehavioralEvent,
    Investor,
    InvestorPreference,
    Startup,
)


def banner(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m")


def main(fast: bool = False, skip_train: bool = False) -> None:
    t0 = time.time()

    banner("[1/7] Rebuilding schema")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("  tables:", len(Base.metadata.tables))

    db = SessionLocal()
    try:
        banner("[2/7] Loading Indian startup funding data (real, 2015-2021)")
        from app.seed.loader import (
            attach_synthetic_financials,
            load_indian_funding,
            load_yc,
        )

        res = load_indian_funding(db)
        db.commit()
        print(f"  startups: {res['startups']}   funding rounds: {res['rounds']}")

        banner("[3/7] Loading Y Combinator companies (real, with outcome labels)")
        yc = load_yc(db, india_only=fast)
        db.commit()
        print(f"  startups: {yc['startups']}" + ("  (India subset)" if fast else ""))

        banner("[4/7] Deriving financial profiles + seeding founder enrichment")
        n = attach_synthetic_financials(db)
        db.commit()
        print(f"  financial rows: {n}")

        from app.seed.founders import seed_founders

        fres = seed_founders(db)
        print(f"  founders: {fres['founders']}   enrichment records: {fres['enrichment_records']}")

        if not skip_train:
            banner("[5/7] Training models")
            from app.ml.train import train_fraud_model, train_growth_model

            print(" growth model (on YC outcome labels):")
            train_growth_model()
            print("\n fraud / anomaly detector:")
            train_fraud_model()
        else:
            banner("[5/7] Skipping training (--skip-train)")

        banner("[6/7] Scoring every startup")
        from app.ml.scoring import score_all

        scored = score_all(db)
        print(f"  scored: {scored}")

        banner("[7/7] Seeding demo investors + behavioural history")
        seed_investors(db)
        db.commit()

        from app.ml import rag

        n_indexed = rag.INDEX.build(db)
        print(f"  vector index: {n_indexed} documents")

    finally:
        db.close()

    print(f"\n\033[32mBootstrap complete in {time.time() - t0:.1f}s\033[0m")
    print("  Start the API:  uvicorn app.main:app --reload --port 8000")


def seed_investors(db) -> None:
    """Three investor personas with different mandates.

    Deliberately varied so the feed visibly differs between them --- a matching
    engine that returns the same list for a fintech seed angel and a growth-stage
    climate fund is not actually matching anything.
    """
    rng = random.Random(7)

    personas = [
        {
            "name": "Ananya Krishnan",
            "email": "ananya@sequoiaindia.example",
            "investor_type": "vc_fund",
            "firm_name": "Peak XV Partners",
            "sebi_registration_no": "IN/AIF2/21-22/0912",
            "accredited_investor": True,
            "pref": {
                "ticket_size_min": 500_000,
                "ticket_size_max": 8_000_000,
                "stage_preference": ["series_a", "series_b_plus"],
                "preferred_sectors": ["FinTech", "Enterprise Software", "AI / ML"],
                "geographic_preference": ["Bangalore", "Mumbai"],
                "risk_tolerance": "medium",
            },
            "likes": ["FinTech", "Enterprise Software"],
        },
        {
            "name": "Rohan Desai",
            "email": "rohan@angel.example",
            "investor_type": "angel",
            "firm_name": None,
            "sebi_registration_no": None,
            "accredited_investor": False,
            "pref": {
                "ticket_size_min": 10_000,
                "ticket_size_max": 250_000,
                "stage_preference": ["idea", "seed"],
                "preferred_sectors": ["Consumer Internet", "E-Commerce", "EdTech"],
                "geographic_preference": ["Bangalore", "Pune"],
                "risk_tolerance": "high",
            },
            "likes": ["Consumer Internet", "E-Commerce"],
        },
        {
            "name": "Meera Raghavan",
            "email": "meera@familyoffice.example",
            "investor_type": "family_office",
            "firm_name": "Raghavan Family Office",
            "sebi_registration_no": "IN/AIF1/20-21/0455",
            "accredited_investor": True,
            "pref": {
                "ticket_size_min": 1_000_000,
                "ticket_size_max": 20_000_000,
                "stage_preference": ["series_b_plus", "growth"],
                "preferred_sectors": ["HealthTech", "ClimateTech", "AgriTech"],
                "geographic_preference": ["Mumbai", "Hyderabad", "Chennai"],
                "risk_tolerance": "low",
            },
            "likes": ["HealthTech", "AgriTech"],
        },
    ]

    for p in personas:
        inv = Investor(
            name=p["name"],
            email=p["email"],
            investor_type=p["investor_type"],
            firm_name=p["firm_name"],
            sebi_registration_no=p["sebi_registration_no"],
            accredited_investor=p["accredited_investor"],
            kyc_status="verified" if p["sebi_registration_no"] else "pending",
        )
        db.add(inv)
        db.flush()
        db.add(InvestorPreference(investor_id=inv.investor_id, **p["pref"]))

        # Behavioural history matching the persona, so the feed has something
        # real to learn from rather than sitting in cold start forever.
        liked = (
            db.query(Startup)
            .filter(Startup.sector.in_(p["likes"]))
            .limit(60)
            .all()
        )
        rng.shuffle(liked)
        for s in liked[:22]:
            for etype, val in [
                ("view", None),
                ("time_spent", {"seconds": rng.randint(15, 240)}),
                ("save", None) if rng.random() > 0.55 else ("view", None),
            ]:
                db.add(
                    BehavioralEvent(
                        investor_id=inv.investor_id,
                        startup_id=s.startup_id,
                        event_type=etype,
                        event_value=val,
                    )
                )

        # A few dismissals outside the mandate, so the penalty logic is live.
        disliked = (
            db.query(Startup)
            .filter(~Startup.sector.in_(p["likes"]))
            .limit(30)
            .all()
        )
        rng.shuffle(disliked)
        for s in disliked[:6]:
            db.add(
                BehavioralEvent(
                    investor_id=inv.investor_id,
                    startup_id=s.startup_id,
                    event_type="dismiss",
                )
            )

        print(f"  {p['name']:20s} ({p['investor_type']:13s}) -> {inv.investor_id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="India-only YC subset")
    ap.add_argument("--skip-train", action="store_true")
    args = ap.parse_args()
    main(fast=args.fast, skip_train=args.skip_train)
