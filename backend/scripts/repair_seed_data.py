"""Repair seeded corpus data in place, without rebuilding the database.

`bootstrap.py` drops and recreates everything, which also throws away live
registrations and accounts. This applies the same two corrections to an
existing database, touching only rows that came from the seed loaders:

1. **Burn rates in proportion to the capital raised.** The India funding
   records carry no headcount, and the loader used to draw a random 3-40
   person team for those companies. A company that raised $2.1bn was then
   modelled as five people burning $25k a month against a billion in cash,
   which the interface reported as 49,839 months of runway.

2. **Anonymous founders for corpus companies.** The loader invented human
   names and `linkedin.com/in/...` links for companies it never collected
   founders for, so a real company's page named people who had nothing to do
   with it. The modelled credibility signals stay; the fabricated identity
   goes.

Idempotent: run it as often as you like. Rescore afterwards, because burn and
runway feed the risk score:

    .venv/bin/python scripts/repair_seed_data.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.enrichment.adapters import _seed_for  # noqa: E402
from app.models import Founder, Startup, StartupFinancials  # noqa: E402

# Anything a human actually registered is left alone.
SEEDED = ("seed_yc", "seed_india_funding")


def drop_implausible_rounds(db) -> dict[str, int]:
    """Remove rounds the public datasets got wrong by orders of magnitude."""
    from app.models import FundingRound
    from app.seed.loader import MAX_PLAUSIBLE_ROUND_USD

    bad = (
        db.query(FundingRound)
        .filter(FundingRound.amount_usd > MAX_PLAUSIBLE_ROUND_USD)
        .all()
    )
    affected = {r.startup_id for r in bad}
    for r in bad:
        db.delete(r)
    db.flush()

    # Re-total the companies that lost a round, so the profile stops showing a
    # funding figure that included it.
    for startup_id in affected:
        total = sum(
            r.amount_usd or 0
            for r in db.query(FundingRound).filter(FundingRound.startup_id == startup_id)
        )
        for fin in db.query(StartupFinancials).filter(
            StartupFinancials.startup_id == startup_id
        ):
            fin.total_funding_usd = round(total, 2) or None
    db.commit()
    return {"implausible_rounds_dropped": len(bad), "companies_retotalled": len(affected)}


def repair_yc_founding_dates(db) -> dict[str, int]:
    """Replace YC batch years masquerading as founding dates with the batch.

    The YC directory has no founding year, so the loader used to store the
    accelerator batch year as `founded_date`. BharatX (YC W22, founded 2019)
    therefore showed "Founded 2022", and the registration agent treated that as
    a source corroborating the same wrong year.
    """
    import json

    from app.core.config import DATA_RAW

    path = DATA_RAW / "yc_companies_all.json"
    if not path.exists():
        return {"yc_batches_recorded": 0, "false_founding_dates_cleared": 0}
    batches = {
        (c.get("slug") or "").lower(): (c.get("batch") or "").strip()
        for c in json.load(path.open())
        if c.get("batch")
    }

    recorded = cleared = 0
    for s in db.query(Startup).filter(Startup.source == "seed_yc").all():
        batch = batches.get((s.slug or "").lower())
        if batch and s.yc_batch != batch:
            s.yc_batch = batch
            recorded += 1
        # The YC directory has no founding year at all: batch-year dates land
        # on 1 January, and the rest came from `launched_at`, which is when the
        # YC profile went up. Neither is a founding date, so none are kept.
        if s.founded_date:
            s.founded_date = None
            cleared += 1
    db.commit()
    return {"yc_batches_recorded": recorded, "false_founding_dates_cleared": cleared}


def repair_sectors(db) -> dict[str, int]:
    """Re-derive each India-funding company's sector by majority vote.

    The loader used to take the sector off whichever round row created the
    company, so Dunzo --- three of whose five rows say "Transportation and
    Tourism" --- came out as Enterprise Software.
    """
    import csv

    from app.core.config import DATA_RAW
    from app.seed.loader import _canon_sector, _norm_name

    votes: dict[str, list[str]] = {}
    files = [
        ("startup_funding_modified.csv", "Startup Name", "Industry Vertical", "utf-8"),
        ("startup_funding2021.csv", "Company/Brand", "Sector", "utf-8-sig"),
    ]
    for filename, name_col, sector_col, encoding in files:
        path = DATA_RAW / filename
        if not path.exists():
            continue
        with path.open(encoding=encoding, errors="replace") as fh:
            for row in csv.DictReader(fh):
                name = (row.get(name_col) or "").strip()
                if len(name) < 2:
                    continue
                votes.setdefault(_norm_name(name), []).append(_canon_sector(row.get(sector_col)))

    changed = 0
    for s in db.query(Startup).filter(Startup.source == "seed_india_funding").all():
        useful = [v for v in votes.get(s.slug or _norm_name(s.legal_name), []) if v != "Other"]
        if not useful:
            continue
        best = Counter(useful).most_common(1)[0][0]
        if best != s.sector:
            s.sector = best
            changed += 1
    db.commit()
    return {"sectors_corrected": changed}


def repair_financials(db) -> dict[str, int]:
    rows = (
        db.query(StartupFinancials, Startup)
        .join(Startup, Startup.startup_id == StartupFinancials.startup_id)
        .filter(Startup.source.in_(SEEDED))
        .all()
    )
    fixed = 0
    for fin, s in rows:
        raised = fin.total_funding_usd
        if not raised or not fin.cash_balance:
            continue
        # Same rule as the loader, and seeded from the company name so a repair
        # run and a fresh bootstrap agree.
        rng = _seed_for("financials-repair", s.legal_name)
        team = s.employee_count or int(
            min(max(raised / rng.uniform(120_000, 260_000), 3), 6_000)
        )
        burn = round(team * rng.uniform(2_500, 7_000), 2)
        # Dropping an implausible round leaves a cash balance that was derived
        # from the old total --- Alteria Capital kept $62.9bn in the bank
        # against $140m raised. Cash is a fraction of the money raised.
        if fin.cash_balance > raised:
            fin.cash_balance = round(raised * rng.uniform(0.15, 0.75), 2)
            fin.burn_rate_monthly = burn
            fixed += 1
            continue
        # Only touch rows the old rule got wrong: a runway beyond ~12 years
        # means burn and cash were drawn on different scales.
        if fin.burn_rate_monthly and fin.cash_balance / fin.burn_rate_monthly <= 150:
            continue
        fin.burn_rate_monthly = burn
        fixed += 1
    db.commit()
    return {"financials_repaired": fixed, "financials_seen": len(rows)}


def repair_founders(db) -> dict[str, int]:
    founders = (
        db.query(Founder)
        .join(Startup, Startup.startup_id == Founder.startup_id)
        .filter(Startup.source.in_(SEEDED))
        .all()
    )
    by_startup: dict[str, list[Founder]] = {}
    for f in founders:
        by_startup.setdefault(f.startup_id, []).append(f)

    renamed = 0
    for rows in by_startup.values():
        # CEO first, so the numbering matches the order they are displayed in.
        ordered = sorted(rows, key=lambda r: ("CEO" not in (r.role or ""), r.founder_id))
        for j, f in enumerate(ordered):
            wanted = f"Founder {j + 1} (modelled)"
            if f.name != wanted or f.linkedin_url or f.github_username:
                f.name = wanted
                f.linkedin_url = None
                f.github_username = None
                renamed += 1
    db.commit()
    return {"founders_anonymised": renamed, "founders_seen": len(founders)}


def main() -> None:
    db = SessionLocal()
    try:
        out = {
            **drop_implausible_rounds(db),
            **repair_yc_founding_dates(db),
            **repair_sectors(db),
            **repair_financials(db),
            **repair_founders(db),
        }
    finally:
        db.close()
    for k, v in out.items():
        print(f"  {k}: {v:,}")
    print("\nNow rescore, because burn and runway feed the risk score:")
    print("  .venv/bin/python -c 'from app.core.database import SessionLocal;"
          " from app.ml.scoring import score_all; d=SessionLocal(); print(score_all(d))'")


if __name__ == "__main__":
    main()
