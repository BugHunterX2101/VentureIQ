"""Feature Store (report section 7, Layer 3).

Turns DB rows into the numeric feature vectors the scoring models consume.
Every derived ratio lives here rather than in the models, so growth, risk, fraud
and founder scoring all read the same definitions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
from sqlalchemy.orm import Session

from app.models import Founder, Startup, StartupFinancials

FINANCIAL_FEATURES = [
    "log_revenue",
    "log_burn",
    "runway_months",
    "ltv_cac_ratio",
    "revenue_growth_pct",
    "log_total_funding",
    "burn_per_head",
    "revenue_per_head",
    "sam_tam_ratio",
    "gst_revenue_deviation",
]


def _safe_log(x: float | None) -> float:
    if x is None or x <= 0:
        return 0.0
    return float(np.log1p(x))


def company_age_years(s: Startup) -> float:
    if not s.founded_date:
        # The growth model was trained on `2026 - batch_year` for YC companies,
        # so keep feeding it exactly that where the batch is all we have. It is
        # years-since-batch rather than true age, but train and serve agree,
        # which is what the model needs.
        if s.yc_batch:
            year = next((int(t) for t in s.yc_batch.split() if t.isdigit()), None)
            if year:
                return max(0.0, float(date.today().year - year))
        return 3.0
    today = date.today()
    fd = s.founded_date
    if isinstance(fd, datetime):
        fd = fd.date()
    return max(0.0, (today - fd).days / 365.25)


def gst_deviation(f: StartupFinancials | None) -> float | None:
    """Fractional gap between founder-reported and GSTN-reported revenue.

    This is the single most load-bearing verification signal in the platform:
    it is the one number a founder cannot inflate without the tax filing
    disagreeing (report section 8.1.2).
    """
    if not f or not f.revenue or not f.gst_reported_revenue:
        return None
    if f.revenue <= 0:
        return None
    return abs(f.revenue - f.gst_reported_revenue) / f.revenue


def financial_vector(s: Startup) -> dict[str, float]:
    f = s.latest_financials
    team = float(s.employee_count or 0) or 1.0

    dev = gst_deviation(f)
    return {
        "log_revenue": _safe_log(f.revenue if f else None),
        "log_burn": _safe_log(f.burn_rate_monthly if f else None),
        "runway_months": float(f.runway_months) if f and f.runway_months else 0.0,
        "ltv_cac_ratio": float(f.ltv_cac_ratio) if f and f.ltv_cac_ratio else 0.0,
        "revenue_growth_pct": float(f.revenue_growth_pct) if f and f.revenue_growth_pct else 0.0,
        "log_total_funding": _safe_log(f.total_funding_usd if f else None),
        "burn_per_head": (f.burn_rate_monthly / team) if f and f.burn_rate_monthly else 0.0,
        "revenue_per_head": (f.revenue / team) if f and f.revenue else 0.0,
        "sam_tam_ratio": (
            (f.sam_usd / f.tam_usd) if f and f.tam_usd and f.sam_usd and f.tam_usd > 0 else 0.0
        ),
        "gst_revenue_deviation": dev if dev is not None else 0.0,
    }


def financial_feature_matrix(db: Session) -> tuple[np.ndarray, list[str], list[str]]:
    """All startups that have financials -> (matrix, startup_ids, feature_names)."""
    startups = (
        db.query(Startup).join(StartupFinancials, isouter=False).distinct().all()
    )
    rows, ids = [], []
    for s in startups:
        if not s.financials:
            continue
        vec = financial_vector(s)
        rows.append([vec[k] for k in FINANCIAL_FEATURES])
        ids.append(s.startup_id)
    if not rows:
        return np.empty((0, len(FINANCIAL_FEATURES))), [], FINANCIAL_FEATURES
    return np.array(rows, dtype=float), ids, FINANCIAL_FEATURES


def founder_vector(founders: list[Founder]) -> dict[str, float]:
    """Aggregate the founding team into one feature set.

    Max, not mean, for exits and experience: one founder with a prior exit is a
    strong team-level signal and averaging it away across co-founders loses that.
    """
    if not founders:
        return {
            "n_founders": 0.0, "max_prior_exits": 0.0, "max_domain_years": 0.0,
            "total_github_commits": 0.0, "max_github_followers": 0.0,
            "linkedin_coverage": 0.0, "github_coverage": 0.0,
        }

    def _mx(attr: str) -> float:
        vals = [getattr(f, attr) or 0 for f in founders]
        return float(max(vals)) if vals else 0.0

    return {
        "n_founders": float(len(founders)),
        "max_prior_exits": _mx("prior_exits"),
        "max_domain_years": _mx("domain_experience_years"),
        "total_github_commits": float(
            sum(f.github_commit_count_90d or 0 for f in founders)
        ),
        "max_github_followers": _mx("github_followers"),
        "linkedin_coverage": sum(1 for f in founders if f.linkedin_url) / len(founders),
        "github_coverage": sum(1 for f in founders if f.github_username) / len(founders),
    }


def text_blob(s: Startup) -> str:
    parts = [s.legal_name, s.one_liner, s.long_description, s.sector, s.sub_vertical]
    return " ".join(p for p in parts if p)


def model_row(s: Startup) -> dict[str, object]:
    """Shape a Startup into the exact row layout `growth_model` expects."""
    from app.ml.train import _region_bucket  # noqa: PLC0415

    stage_map = {
        "idea": "Idea", "seed": "Seed", "series_a": "Early",
        "series_b_plus": "Growth", "growth": "Growth",
    }
    desc = s.long_description or s.one_liner or ""
    return {
        "team_size": float(s.employee_count or 0),
        "company_age_years": company_age_years(s),
        "n_tags": float(len((s.sub_vertical or "").split(",")) if s.sub_vertical else 0),
        "description_length": float(len(desc)),
        "is_top_company": 0.0,
        "industry": s.sector or "Unknown",
        "region_bucket": _region_bucket(None, s.hq_city or ""),
        "stage_bucket": stage_map.get(s.stage, "Unknown"),
        "description": desc,
    }


def months_since(d: date | datetime | None) -> float | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return (date.today() - d).days / 30.44


def utcnow() -> datetime:
    return datetime.now(UTC)
