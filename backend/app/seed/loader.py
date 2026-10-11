"""ETL from data/raw into the database.

Two sources, two very different roles:

* The Indian funding CSVs give us realistic Indian companies, sectors, cities
  and funding amounts --- but no outcome labels. These populate the marketplace.
* The YC JSON gives us 6,151 companies WITH real outcome labels (Active /
  Inactive / Acquired / Public). That label is the only ground truth available
  anywhere in the seed data, so it is what the growth model trains on
  (docs/BUILD_PLAN.md Problem 3).
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import DATA_RAW
from app.models import FundingRound, Startup, StartupFinancials

# Map the messy free-text sectors in the seed CSVs onto one taxonomy.
SECTOR_CANON = {
    "fintech": "FinTech",
    "financial services": "FinTech",
    "banking and financial services": "FinTech",
    "finance": "FinTech",
    "ecommerce": "E-Commerce",
    "e-commerce": "E-Commerce",
    "e-commerce and retail": "E-Commerce",
    "ecommerce & retail": "E-Commerce",
    "consumer internet": "Consumer Internet",
    "technology": "Enterprise Software",
    "saas": "Enterprise Software",
    "enterprise software": "Enterprise Software",
    "software": "Enterprise Software",
    "b2b software": "Enterprise Software",
    "ai startup": "AI / ML",
    "artificial intelligence": "AI / ML",
    "ai": "AI / ML",
    "machine learning": "AI / ML",
    "deeptech": "AI / ML",
    "healthcare": "HealthTech",
    "healthtech": "HealthTech",
    "health care": "HealthTech",
    "health and wellness": "HealthTech",
    "pharmaceutical": "HealthTech",
    "edtech": "EdTech",
    "education": "EdTech",
    "logistics": "Logistics & Mobility",
    "logistics and transportation": "Logistics & Mobility",
    "transportation": "Logistics & Mobility",
    "automotive": "Logistics & Mobility",
    "mobility": "Logistics & Mobility",
    "agriculture": "AgriTech",
    "agritech": "AgriTech",
    "agriculture and food production": "AgriTech",
    "food and beverage": "Food & Beverage",
    "food & beverages": "Food & Beverage",
    "foodtech": "Food & Beverage",
    "real estate": "PropTech",
    "proptech": "PropTech",
    "gaming": "Gaming & Media",
    "media and entertainment": "Gaming & Media",
    "entertainment": "Gaming & Media",
    "manufacturing": "Industrials",
    "industrials": "Industrials",
    "energy": "ClimateTech",
    "clean energy": "ClimateTech",
    "climate tech": "ClimateTech",
}

STATE_BY_CITY = {
    "bangalore": "Karnataka", "bengaluru": "Karnataka",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "new delhi": "Delhi", "delhi": "Delhi", "noida": "Uttar Pradesh",
    "gurgaon": "Haryana", "gurugram": "Haryana", "faridabad": "Haryana",
    "hyderabad": "Telangana", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "kolkata": "West Bengal", "ahmedabad": "Gujarat", "surat": "Gujarat",
    "jaipur": "Rajasthan", "kochi": "Kerala", "indore": "Madhya Pradesh",
    "chandigarh": "Chandigarh", "lucknow": "Uttar Pradesh",
}

# Funding-round language -> our stage enum.
STAGE_BY_ROUND = {
    "seed": "seed", "seed round": "seed", "seed funding": "seed",
    "pre-seed": "idea", "pre seed": "idea", "angel": "seed", "angel round": "seed",
    "maiden round": "seed", "private equity": "growth",
    "series a": "series_a", "pre-series a": "seed", "series b": "series_b_plus",
    "series c": "growth", "series d": "growth", "series e": "growth",
    "series f": "growth", "debt funding": "growth",
}


# YC's own taxonomy. Its top-level `industry` is too coarse to be useful for
# investor matching --- "B2B" alone covers 3,140 of 6,151 companies, which is not
# a sector anyone has a mandate for. The `subindustry` field is far more
# granular, so we map from that first and only fall back to the top level.
YC_SUBINDUSTRY_CANON = {
    "fintech": "FinTech", "payments": "FinTech", "finance and accounting": "FinTech",
    "banking and exchange": "FinTech", "asset management": "FinTech",
    "credit and lending": "FinTech", "insurance": "FinTech",
    "healthcare it": "HealthTech", "consumer health and wellness": "HealthTech",
    "therapeutics": "HealthTech", "diagnostics": "HealthTech",
    "drug discovery and delivery": "HealthTech", "medical devices": "HealthTech",
    "healthcare services": "HealthTech", "industrial bio": "HealthTech",
    "engineering, product and design": "Enterprise Software",
    "infrastructure": "Enterprise Software", "productivity": "Enterprise Software",
    "operations": "Enterprise Software", "sales": "Enterprise Software",
    "marketing": "Enterprise Software", "analytics": "Enterprise Software",
    "security": "Enterprise Software", "legal": "Enterprise Software",
    "human resources": "Enterprise Software", "recruiting and talent": "Enterprise Software",
    "office management": "Enterprise Software", "b2b": "Enterprise Software",
    "manufacturing and robotics": "Industrials", "drones": "Industrials",
    "aviation and space": "Industrials", "automotive": "Logistics & Mobility",
    "supply chain and logistics": "Logistics & Mobility",
    "energy": "ClimateTech", "climate": "ClimateTech", "agriculture": "AgriTech",
    "retail": "E-Commerce", "e-commerce": "E-Commerce",
    "education": "EdTech",
    "home and personal": "Consumer Internet", "social": "Consumer Internet",
    "content": "Consumer Internet", "consumer": "Consumer Internet",
    "travel, leisure and tourism": "Consumer Internet",
    "food and beverage": "Food & Beverage",
    "gaming": "Gaming & Media", "virtual and augmented reality": "Gaming & Media",
    "apparel and cosmetics": "Consumer Internet",
    "real estate and construction": "PropTech", "construction": "PropTech",
    "government": "GovTech",
}

AI_TAGS = {"ai", "artificial intelligence", "machine learning", "generative ai",
           "aiops", "ai assistant", "llm", "nlp", "computer vision", "conv-ai"}


# Null-ish strings that appear literally in the CSVs (pandas writes "nan").
NULLISH = {"", "nan", "none", "null", "-", "n/a", "na", "unspecified", "undisclosed"}


def _clean(raw: str | None) -> str | None:
    """Free-text CSV fields carry literal "nan"/"none" strings. Anything
    null-ish becomes a real None so the UI renders an em dash, not "nan"."""
    if raw is None:
        return None
    v = raw.strip()
    return None if v.lower() in NULLISH else v


def _canon_sector(raw: str | None) -> str:
    if not raw or raw.strip().lower() in NULLISH:
        return "Other"
    key = raw.strip().lower()
    if key in SECTOR_CANON:
        return SECTOR_CANON[key]
    for frag, canon in SECTOR_CANON.items():
        if frag in key:
            return canon
    return raw.strip().title()[:96] or "Other"


def _canon_yc_sector(company: dict[str, Any]) -> str:
    """Prefer subindustry; promote to AI / ML when the tags say so.

    AI is a sector investors explicitly filter on, but YC encodes it in `tags`
    rather than in the industry hierarchy, so it would otherwise be invisible.
    """
    tags = {t.strip().lower() for t in (company.get("tags") or [])}
    if tags & AI_TAGS:
        return "AI / ML"

    sub = (company.get("subindustry") or "").split("->")[-1].strip().lower()
    if sub in YC_SUBINDUSTRY_CANON:
        return YC_SUBINDUSTRY_CANON[sub]

    industry = (company.get("industry") or "").strip().lower()
    if industry in YC_SUBINDUSTRY_CANON:
        return YC_SUBINDUSTRY_CANON[industry]
    if industry in {"unspecified", ""}:
        return "Other"
    return _canon_sector(company.get("industry"))


def _canon_stage(raw: str | None) -> str:
    if not raw:
        return "seed"
    key = raw.strip().lower()
    return STAGE_BY_ROUND.get(key, "seed")


# No Indian private round in this period came close to this. The public
# datasets carry occasional typos --- one row lists Alteria Capital, a venture
# debt fund, at "$150,000,000,000" where the real figure is three orders of
# magnitude smaller. Importing that verbatim puts "$150.1B raised" on a company
# page, which is worse than having no figure at all. We cannot know what was
# meant, so the round is dropped rather than guessed at.
MAX_PLAUSIBLE_ROUND_USD = 5e9


def _parse_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    if not cleaned or cleaned == ".":
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if val > MAX_PLAUSIBLE_ROUND_USD:
        return None
    return val if val > 0 else None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip().replace(".", "/").replace("-", "/")
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _split_investors(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r",|/|\band\b|&", raw)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2][:12]


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _infer_stage_from_team(team_size: int | None, batch_year: int | None) -> str:
    """YC companies have no explicit stage; approximate from headcount + age."""
    ts = team_size or 0
    if ts >= 200:
        return "growth"
    if ts >= 50:
        return "series_b_plus"
    if ts >= 15:
        return "series_a"
    if ts >= 3:
        return "seed"
    return "idea"


def load_indian_funding(db: Session, limit: int | None = None) -> dict[str, int]:
    """Load the 2015-2019 Kaggle-mirror CSV plus the 2021 file.

    Companies appear across multiple funding rounds; we dedupe on a normalised
    name and attach each row as a FundingRound.
    """
    created = 0
    rounds = 0
    by_name: dict[str, Startup] = {}
    # One company's rounds can each carry a different industry label. Dunzo's
    # five rows say "Career, Special Duties and Personal Development",
    # "Information Technology (IT)" and "Transportation and Tourism" three
    # times. Taking whichever row happened to create the company made Dunzo
    # "Enterprise Software"; a vote across its rows gets it right, and sector
    # feeds both the peer cohort and the growth model.
    sector_votes: dict[str, list[str]] = {}

    # --- 2015-2019 file: has dates, investors, round type -----------------
    path = DATA_RAW / "startup_funding_modified.csv"
    if path.exists():
        with path.open(encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("Startup Name") or "").strip()
                if not name or len(name) < 2:
                    continue
                key = _norm_name(name)
                city = (row.get("City  Location") or row.get("City Location") or "").strip()
                if city.lower() in NULLISH:
                    city = ""
                stage = _canon_stage(row.get("InvestmentnType"))

                startup = by_name.get(key)
                if startup is None:
                    startup = Startup(
                        legal_name=name,
                        slug=key,
                        stage=stage,
                        sector=_canon_sector(row.get("Industry Vertical")),
                        sub_vertical=_clean(row.get("SubVertical")),
                        hq_city=city or None,
                        hq_state=STATE_BY_CITY.get(city.lower()),
                        source="seed_india_funding",
                        one_liner=_clean(row.get("SubVertical")),
                    )
                    db.add(startup)
                    db.flush()
                    by_name[key] = startup
                    created += 1
                    if limit and created >= limit:
                        break

                sector_votes.setdefault(key, []).append(
                    _canon_sector(row.get("Industry Vertical"))
                )
                amount = _parse_amount(row.get("Amount in USD"))
                db.add(
                    FundingRound(
                        startup_id=startup.startup_id,
                        round_stage=(row.get("InvestmentnType") or "").strip() or None,
                        amount_usd=amount,
                        announced_date=_parse_date(row.get("Date ddmmyyyy")),
                        investor_names=_split_investors(row.get("Investors Name")),
                    )
                )
                rounds += 1

    # --- 2021 file: adds founders, "what it does", explicit stage ----------
    path = DATA_RAW / "startup_funding2021.csv"
    if path.exists() and not (limit and created >= limit):
        with path.open(encoding="utf-8-sig", errors="replace") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("Company/Brand") or "").strip()
                if not name or len(name) < 2:
                    continue
                key = _norm_name(name)
                city = (row.get("HeadQuarter") or "").strip()
                if city.lower() in NULLISH:
                    city = ""
                startup = by_name.get(key)

                if startup is None:
                    founded = None
                    fy = (row.get("Founded") or "").strip()
                    if fy.isdigit() and 1900 < int(fy) < 2030:
                        founded = date(int(fy), 1, 1)

                    startup = Startup(
                        legal_name=name,
                        slug=key,
                        stage=_canon_stage(row.get("Stage")),
                        sector=_canon_sector(row.get("Sector")),
                        hq_city=city or None,
                        hq_state=STATE_BY_CITY.get(city.lower()),
                        founded_date=founded,
                        one_liner=(_clean(row.get("What it does")) or "")[:280] or None,
                        long_description=_clean(row.get("What it does")),
                        source="seed_india_funding",
                    )
                    db.add(startup)
                    db.flush()
                    by_name[key] = startup
                    created += 1
                    if limit and created >= limit:
                        break
                elif not startup.long_description:
                    startup.long_description = _clean(row.get("What it does"))
                    if startup.long_description:
                        startup.one_liner = startup.one_liner or startup.long_description[:280]

                sector_votes.setdefault(key, []).append(_canon_sector(row.get("Sector")))
                db.add(
                    FundingRound(
                        startup_id=startup.startup_id,
                        round_stage=(row.get("Stage") or "").strip() or None,
                        amount_usd=_parse_amount(row.get("Amount($)")),
                        announced_date=date(2021, 1, 1),
                        investor_names=_split_investors(row.get("Investor")),
                    )
                )
                rounds += 1

    # Majority sector, ignoring rows that told us nothing.
    resectored = 0
    for key, votes in sector_votes.items():
        startup = by_name.get(key)
        useful = [v for v in votes if v != "Other"]
        if not startup or not useful:
            continue
        best = Counter(useful).most_common(1)[0][0]
        if best != startup.sector:
            startup.sector = best
            resectored += 1

    db.flush()
    return {"startups": created, "rounds": rounds, "resectored": resectored}


def load_yc(db: Session, india_only: bool = False, limit: int | None = None) -> dict[str, int]:
    """Load YC companies. These carry the outcome label the model trains on."""
    fname = "yc_companies_india.json" if india_only else "yc_companies_all.json"
    path = DATA_RAW / fname
    if not path.exists():
        return {"startups": 0}

    with path.open() as fh:
        companies: list[dict[str, Any]] = json.load(fh)

    created = 0
    for c in companies:
        name = (c.get("name") or "").strip()
        if not name:
            continue

        batch = c.get("batch") or ""
        m = re.search(r"(\d{4})", batch)
        batch_year = int(m.group(1)) if m else None
        # The YC directory carries no founding year --- only the batch, and a
        # `launched_at` timestamp for when the YC profile went up. Neither is
        # when the company was founded, so neither is recorded as one.
        founded = None

        locations = c.get("all_locations") or ""
        city = locations.split(",")[0].strip() if locations else None

        startup = Startup(
            legal_name=name,
            slug=c.get("slug") or _norm_name(name),
            stage=_infer_stage_from_team(c.get("team_size"), batch_year),
            sector=_canon_yc_sector(c),
            sub_vertical=_clean((c.get("subindustry") or "").split("->")[-1]),
            founded_date=founded,
            yc_batch=batch or None,
            hq_city=city,
            website=c.get("website"),
            one_liner=(_clean(c.get("one_liner")) or "")[:280] or None,
            long_description=_clean(c.get("long_description")),
            employee_count=c.get("team_size"),
            status=(c.get("status") or "").lower() or None,
            source="seed_yc",
            verified=True,  # YC-confirmed participation is itself a verification signal
        )
        db.add(startup)
        created += 1
        if limit and created >= limit:
            break

    db.flush()
    return {"startups": created}


def attach_synthetic_financials(db: Session) -> int:
    """Derive a financials row from real funding history where we have it.

    Seed CSVs carry funding amounts but no P&L --- no public dataset does (see
    data/raw/README.md). Rather than inventing numbers out of nothing, we derive
    a plausible financial profile FROM the real funding total and real headcount,
    and mark the source so nothing downstream mistakes it for reported data.
    """
    import random

    rng = random.Random(42)  # deterministic: reruns produce the same DB
    count = 0

    startups = db.query(Startup).all()
    totals: dict[str, float] = {}
    for r in db.query(FundingRound).all():
        if r.amount_usd:
            totals[r.startup_id] = totals.get(r.startup_id, 0.0) + r.amount_usd

    for s in startups:
        raised = totals.get(s.startup_id)
        team = s.employee_count or 0

        if not raised and s.source == "seed_yc" and team:
            # YC company with no round data: infer scale from headcount.
            raised = team * rng.uniform(40_000, 120_000)
        if not raised:
            continue
        if not team:
            # Headcount is missing from the India funding records. Drawing a
            # random 3-40 person team for a company that raised hundreds of
            # millions produced burn rates of a few thousand dollars against a
            # billion in cash --- and runways of 49,000 months. Infer the team
            # from the capital raised instead, so the two stay in proportion.
            team = int(min(max(raised / rng.uniform(120_000, 260_000), 3), 6_000))

        # Burn scales with headcount; runway from what is left of the raise.
        monthly_burn = team * rng.uniform(2_500, 7_000)
        cash = raised * rng.uniform(0.15, 0.75)
        revenue_multiple = {
            "idea": 0.0, "seed": rng.uniform(0.0, 0.3),
            "series_a": rng.uniform(0.2, 0.9), "series_b_plus": rng.uniform(0.6, 2.0),
            "growth": rng.uniform(1.0, 3.5),
        }[s.stage]
        revenue = raised * revenue_multiple
        prior = revenue / rng.uniform(1.2, 3.2) if revenue > 0 else None
        tam = rng.uniform(2e8, 8e10)

        db.add(
            StartupFinancials(
                startup_id=s.startup_id,
                as_of_date=date(2025, 12, 31),
                revenue=round(revenue, 2) if revenue else None,
                prior_year_revenue=round(prior, 2) if prior else None,
                burn_rate_monthly=round(monthly_burn, 2),
                cash_balance=round(cash, 2),
                # LTV is generated as a multiple OF cac, not independently, so
                # the resulting ratios land in a realistic 0.6x-9x band instead
                # of the absurd 200x that independent draws would produce.
                cac=round(cac := rng.uniform(20, 900), 2),
                ltv=round(cac * rng.lognormvariate(0.85, 0.55), 2),
                tam_usd=round(tam, 2),
                sam_usd=round(tam * rng.uniform(0.04, 0.30), 2),
                active_users=int(rng.uniform(500, 900_000)),
                total_funding_usd=round(raised, 2),
                # GST cross-check. Roughly 8% of companies are seeded with a
                # material discrepancy --- a plausible base rate for misreporting.
                # Keep this low: a detector that flags half the population is
                # noise, not signal, and the whole point is a usable alert queue.
                gst_reported_revenue=(
                    round(revenue * rng.choices(
                        [1.0, 0.99, 1.01, 0.98, 1.02, 0.55, 0.42, 1.85],
                        weights=[30, 22, 22, 9, 9, 3, 2, 3],
                        k=1,
                    )[0], 2)
                    if revenue
                    else None
                ),
            )
        )
        count += 1

    db.flush()
    return count
