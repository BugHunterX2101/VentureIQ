"""AI Engine: four independent scores + weighted composite.

Report section 8.3 is explicit that the four scores are computed independently
and only combined at the end, citing the Maarouf et al. ablation showing early
fusion underperforms. That structure is preserved here --- each `_score_*`
function is self-contained and returns its own feature attributions.

Attribution: real SHAP on the tree-based growth model where available, and
explicit additive contributions for the rule-composed scores. The report calls
all of this "SHAP rationale"; docs/BUILD_PLAN.md Problem 6 notes that
explainability necessarily means different mechanisms for different model types,
so each attribution carries a `method` field saying which one produced it.
"""

from __future__ import annotations

from typing import Any

import joblib
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml import explain
from app.ml.features import (
    company_age_years,
    financial_vector,
    founder_vector,
    gst_deviation,
    model_row,
)
from app.ml.train import FRAUD_MODEL_PATH, MODEL_PATH
from app.models import FraudSignal, Score, Startup

# Composite weights. A v1 configuration, not learned --- see report section 8.3.
COMPOSITE_WEIGHTS = {
    "growth_potential": 0.35,
    "risk_level": 0.25,
    "founder_credibility": 0.25,
    "fraud_likelihood": 0.15,
}

_growth_bundle: dict[str, Any] | None = None
_fraud_bundle: dict[str, Any] | None = None


def _load_growth() -> dict[str, Any] | None:
    global _growth_bundle
    if _growth_bundle is None and MODEL_PATH.exists():
        _growth_bundle = joblib.load(MODEL_PATH)
    return _growth_bundle


def _load_fraud() -> dict[str, Any] | None:
    global _fraud_bundle
    if _fraud_bundle is None and FRAUD_MODEL_PATH.exists():
        _fraud_bundle = joblib.load(FRAUD_MODEL_PATH)
    return _fraud_bundle


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, x)))


def _band(score: float) -> str:
    if score >= 75:
        return "strong"
    if score >= 55:
        return "moderate"
    if score >= 35:
        return "weak"
    return "poor"


# --------------------------------------------------------------------------
# 1. Growth potential --- ML model + trajectory signals
# --------------------------------------------------------------------------


def _score_growth(s: Startup, explained: tuple | None = None) -> tuple[float, list[dict], str]:
    """`explained` lets a bulk caller pass in an already-computed decomposition."""
    fin = financial_vector(s)
    contributions: list[dict] = []
    bundle = _load_growth()

    if bundle:
        import pandas as pd

        row = model_row(s)
        # One pass gives both the prediction and its Shapley decomposition;
        # without shap installed, fall back to predicting on its own.
        if explained is None:
            explained = explain.growth_explain(bundle, row)
        if explained:
            proba, attributions, base_rate = explained
        else:
            try:
                proba = float(bundle["model"].predict_proba(pd.DataFrame([row]))[0, 1])
            except Exception:
                proba = 0.35
        base = proba * 100.0
        method = f"model:{bundle.get('algo', 'unknown')}"

        if explained:
            method = f"shap:{bundle.get('algo', 'unknown')}"
            contributions.extend(attributions)
            contributions.append(
                {
                    "feature": "ml_exit_probability",
                    "value": round(proba, 4),
                    # Already split across the attributions above; kept at zero
                    # so the headline never double-counts them.
                    "contribution": 0.0,
                    "direction": "positive" if proba > base_rate / 100.0 else "negative",
                    "label": (
                        f"Model-estimated probability of acquisition/IPO: {proba:.1%} "
                        f"against a {base_rate:.1f}% base rate"
                    ),
                }
            )
        else:
            contributions.append(
                {
                    "feature": "ml_exit_probability",
                    "value": round(proba, 4),
                    "contribution": round(base - 35.0, 2),
                    "direction": "positive" if proba > 0.35 else "negative",
                    "label": f"Model-estimated probability of acquisition/IPO: {proba:.1%}",
                }
            )
    else:
        base = 35.0
        method = "heuristic_only"

    # Trajectory adjustments the classifier cannot see (it was trained on YC
    # metadata, not on P&L, because no public dataset has both).
    growth_pct = fin["revenue_growth_pct"]
    if growth_pct:
        adj = _clamp(growth_pct / 4.0, -15, 25)
        base += adj
        contributions.append(
            {
                "feature": "revenue_growth_pct",
                "value": round(growth_pct, 1),
                "contribution": round(adj, 2),
                "direction": "positive" if adj > 0 else "negative",
                "label": f"Year-on-year revenue growth of {growth_pct:.0f}%",
            }
        )

    ltv_cac = fin["ltv_cac_ratio"]
    if ltv_cac:
        # 3.0 is the conventional healthy LTV:CAC threshold.
        adj = _clamp((ltv_cac - 3.0) * 4.0, -12, 18)
        base += adj
        contributions.append(
            {
                "feature": "ltv_cac_ratio",
                "value": round(ltv_cac, 2),
                "contribution": round(adj, 2),
                "direction": "positive" if adj > 0 else "negative",
                "label": (
                    f"LTV:CAC of {ltv_cac:.1f}x "
                    f"({'above' if ltv_cac >= 3 else 'below'} the 3.0x benchmark)"
                ),
            }
        )

    sam_tam = fin["sam_tam_ratio"]
    if sam_tam:
        adj = _clamp(sam_tam * 30.0, 0, 12)
        base += adj
        contributions.append(
            {
                "feature": "sam_tam_ratio",
                "value": round(sam_tam, 3),
                "contribution": round(adj, 2),
                "direction": "positive",
                "label": f"Serviceable market is {sam_tam:.0%} of total addressable market",
            }
        )

    rev_head = fin["revenue_per_head"]
    if rev_head > 0:
        adj = _clamp(np.log1p(rev_head) * 1.2 - 6, -8, 14)
        base += adj
        contributions.append(
            {
                "feature": "revenue_per_head",
                "value": round(rev_head, 0),
                "contribution": round(adj, 2),
                "direction": "positive" if adj > 0 else "negative",
                "label": f"Revenue per employee of ${rev_head:,.0f}",
            }
        )

    # The headline probability is a zero-weight summary line, so it is kept
    # regardless of rank; everything else competes on absolute contribution.
    headline = [c for c in contributions if c["feature"] == "ml_exit_probability"
                and c["contribution"] == 0.0]
    rest = [c for c in contributions if c not in headline]
    rest.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return _clamp(base), (headline + rest)[:4], method


# --------------------------------------------------------------------------
# 2. Risk level --- higher score = SAFER (consistent direction for the UI)
# --------------------------------------------------------------------------


def _score_risk(s: Startup, cohort_stats: dict | None = None) -> tuple[float, list[dict], str]:
    fin = financial_vector(s)
    base = 60.0
    contributions: list[dict] = []

    runway = fin["runway_months"]
    if runway:
        # 18 months is the conventional "comfortable" runway target.
        adj = _clamp((runway - 12.0) * 2.0, -30, 22)
        base += adj
        contributions.append(
            {
                "feature": "runway_months",
                "value": round(runway, 1),
                "contribution": round(adj, 2),
                "direction": "positive" if adj > 0 else "negative",
                "label": (
                    f"{runway:.0f} months of runway at current burn"
                    + (" — below the 12-month danger line" if runway < 12 else "")
                ),
            }
        )
    else:
        base -= 8
        contributions.append(
            {
                "feature": "runway_months",
                "value": None,
                "contribution": -8.0,
                "direction": "negative",
                "label": "No runway reported — cannot assess capital risk",
            }
        )

    burn_head = fin["burn_per_head"]
    if burn_head:
        # Above ~$8k/head/month is high for an Indian startup cost base.
        adj = _clamp((8000 - burn_head) / 400.0, -18, 12)
        base += adj
        contributions.append(
            {
                "feature": "burn_per_head",
                "value": round(burn_head, 0),
                "contribution": round(adj, 2),
                "direction": "positive" if adj > 0 else "negative",
                "label": f"Monthly burn of ${burn_head:,.0f} per employee",
            }
        )

    if cohort_stats and cohort_stats.get("cohort_size", 0) >= settings.min_cohort_size:
        density = cohort_stats.get("sector_density", 0)
        adj = _clamp(-(density - 30) / 8.0, -12, 6)
        base += adj
        contributions.append(
            {
                "feature": "competitive_density",
                "value": density,
                "contribution": round(adj, 2),
                "direction": "positive" if adj > 0 else "negative",
                "label": f"{density} comparable startups in the same sector and stage",
            }
        )

    age = company_age_years(s)
    if age < 1.0:
        base -= 6
        contributions.append(
            {
                "feature": "company_age_years",
                "value": round(age, 1),
                "contribution": -6.0,
                "direction": "negative",
                "label": f"Only {age * 12:.0f} months old — limited operating history",
            }
        )

    # The register's own verdict on companies that look like this one. Only
    # available for a company we actually matched in the MCA registry, which
    # means a real Indian entity with a CIN --- so it stays a bonus signal, not
    # a requirement, and the rule-based terms above stand on their own.
    method = "rule_additive"
    survival_adj = _survival_signal(s)
    if survival_adj:
        method = "rules+model:survival"
        base += survival_adj["contribution"]
        contributions.append(survival_adj)

    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return _clamp(base), contributions[:3], method


def _survival_signal(s: Startup) -> dict | None:
    """Dissolution risk from the MCA-trained model, as a safety adjustment."""
    if not s.cin:
        return None
    try:
        from app.ml import survival
        from app.registry import store as registry

        if survival.bundle() is None:
            return None
        record = registry.get_local(s.cin)
        if not record:
            return None
        proba = survival.predict(record)
        if proba is None:
            return None
    except Exception:
        return None

    # The population base rate is ~27.5%. Sitting on it is neutral; the swing
    # is capped so one model cannot dominate a score built from several signals.
    adj = _clamp((0.275 - proba) * 40.0, -14, 10)
    if abs(adj) < 0.5:
        return None
    return {
        "feature": "registry_survival",
        "value": round(proba, 4),
        "contribution": round(adj, 2),
        "direction": "positive" if adj > 0 else "negative",
        "label": (
            f"{proba:.0%} of companies with this profile on the MCA register have been "
            f"struck off or dissolved (population average 27%)"
        ),
    }


# --------------------------------------------------------------------------
# 3. Fraud likelihood --- higher score = MORE suspicious
# --------------------------------------------------------------------------


def _score_fraud(s: Startup) -> tuple[float, list[dict], list[dict], str]:
    """Returns (score, attributions, signals_to_persist, method)."""
    fin = financial_vector(s)
    contributions: list[dict] = []
    signals: list[dict] = []
    base = 8.0  # innocent until the data says otherwise

    # --- Rule 1: founder-reported revenue vs GSTN filing ------------------
    dev = gst_deviation(s.latest_financials)
    if dev is not None and dev > settings.deviation_threshold:
        adj = _clamp(dev * 70.0, 0, 45)
        base += adj
        f = s.latest_financials
        contributions.append(
            {
                "feature": "gst_revenue_deviation",
                "value": round(dev, 3),
                "contribution": round(adj, 2),
                "direction": "negative",
                "label": (
                    f"Reported revenue differs from GSTN filings by {dev:.0%} "
                    f"(${f.revenue:,.0f} claimed vs ${f.gst_reported_revenue:,.0f} filed)"
                ),
            }
        )
        signals.append(
            {
                "detector": "rule",
                "anomaly_score": round(min(dev, 1.0), 3),
                "flagged_fields": ["revenue", "gst_reported_revenue"],
                "severity": "high" if dev > 0.5 else "medium",
                "explanation": (
                    f"Self-reported revenue deviates {dev:.0%} from GST-filed revenue, "
                    f"above the {settings.deviation_threshold:.0%} threshold."
                ),
            }
        )

    # --- Rule 2: implausible unit economics -------------------------------
    ltv_cac = fin["ltv_cac_ratio"]
    if ltv_cac and ltv_cac > 25:
        base += 12
        contributions.append(
            {
                "feature": "ltv_cac_ratio",
                "value": round(ltv_cac, 2),
                "contribution": 12.0,
                "direction": "negative",
                "label": f"LTV:CAC of {ltv_cac:.0f}x is implausibly high — likely misstated",
            }
        )
        signals.append(
            {
                "detector": "rule",
                "anomaly_score": 0.6,
                "flagged_fields": ["ltv", "cac"],
                "severity": "medium",
                "explanation": f"LTV:CAC ratio of {ltv_cac:.0f}x far exceeds sector norms.",
            }
        )

    # --- Rule 3: revenue with no plausible headcount to produce it --------
    f = s.latest_financials
    if f and f.revenue and f.revenue > 1_000_000 and (s.employee_count or 0) < 3:
        base += 15
        contributions.append(
            {
                "feature": "revenue_per_head",
                "value": round(fin["revenue_per_head"], 0),
                "contribution": 15.0,
                "direction": "negative",
                "label": (
                    f"${f.revenue:,.0f} revenue reported with "
                    f"{s.employee_count or 0} employees"
                ),
            }
        )

    # --- Model: Isolation Forest + PCA reconstruction error ---------------
    bundle = _load_fraud()
    method = "rules_only"
    if bundle:
        method = "isolation_forest+pca"
        names = bundle["feature_names"]
        vec = np.array([[fin[k] for k in names]], dtype=float)
        scaled = bundle["scaler"].transform(vec)

        # decision_function: negative == outlier.
        iso_raw = float(bundle["isolation_forest"].decision_function(scaled)[0])
        iso_contrib = _clamp(-iso_raw * 90.0, -10, 30)
        base += iso_contrib

        recon = bundle["pca"].inverse_transform(bundle["pca"].transform(scaled))
        err = float(np.mean((scaled - recon) ** 2))
        p95 = bundle["recon_error_p95"]
        if err > p95:
            ratio = err / max(p95, 1e-9)
            adj = _clamp((ratio - 1.0) * 18.0, 0, 25)
            base += adj
            contributions.append(
                {
                    "feature": "autoencoder_reconstruction_error",
                    "value": round(err, 4),
                    "contribution": round(adj, 2),
                    "direction": "negative",
                    "label": (
                        f"Financial profile cannot be reconstructed from learned normal "
                        f"patterns (error {ratio:.1f}x the 95th-percentile threshold)"
                    ),
                }
            )
            signals.append(
                {
                    "detector": "autoencoder",
                    "anomaly_score": round(min(ratio / 3, 1.0), 3),
                    "reconstruction_error": round(err, 5),
                    "flagged_fields": ["financial_profile"],
                    "severity": "high" if ratio > 2.5 else "medium",
                    "explanation": (
                        f"Reconstruction error {err:.4f} exceeds the p95 threshold "
                        f"{p95:.4f} learned from the population."
                    ),
                }
            )

        if iso_raw < 0:
            # Which ratios did the isolating, by Shapley value over path length.
            shap_rows = explain.fraud_attributions(bundle, scaled, iso_contrib)
            if shap_rows:
                method = "shap:isolation_forest+pca"
                contributions.extend(shap_rows)
            contributions.append(
                {
                    "feature": "isolation_forest_score",
                    "value": round(iso_raw, 4),
                    "contribution": 0.0 if shap_rows else round(iso_contrib, 2),
                    "direction": "negative",
                    "label": "Financial profile isolates as an outlier against peer startups",
                }
            )
            signals.append(
                {
                    "detector": "isolation_forest",
                    "anomaly_score": round(min(-iso_raw * 2, 1.0), 3),
                    "flagged_fields": ["financial_profile"],
                    # Only a decisively isolated profile is "high" --- an
                    # over-eager severity ladder buries the real cases.
                    "severity": "low" if iso_raw > -0.05 else ("medium" if iso_raw > -0.12 else "high"),
                    "explanation": (
                        "Isolation Forest separates this profile from the population "
                        "in few splits, indicating structural dissimilarity."
                    ),
                }
            )

    if not contributions:
        contributions.append(
            {
                "feature": "consistency_checks",
                "value": 0,
                "contribution": 0.0,
                "direction": "positive",
                "label": "All cross-source consistency checks passed",
            }
        )

    # Same rule as growth: the zero-weight summary line survives ranking.
    headline = [c for c in contributions if c["feature"] == "isolation_forest_score"
                and c["contribution"] == 0.0]
    rest = [c for c in contributions if c not in headline]
    rest.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return _clamp(base), (headline + rest)[:4], signals, method


# --------------------------------------------------------------------------
# 4. Founder credibility
# --------------------------------------------------------------------------


def _score_founder(s: Startup) -> tuple[float, list[dict], str]:
    fv = founder_vector(list(s.founders))
    contributions: list[dict] = []

    if fv["n_founders"] == 0:
        return (
            25.0,
            [
                {
                    "feature": "n_founders",
                    "value": 0,
                    "contribution": -25.0,
                    "direction": "negative",
                    "label": "No founder profiles on record — credibility cannot be assessed",
                }
            ],
            "insufficient_data",
        )

    base = 42.0

    exits = fv["max_prior_exits"]
    if exits:
        adj = _clamp(exits * 14.0, 0, 28)
        base += adj
        contributions.append(
            {
                "feature": "max_prior_exits",
                "value": int(exits),
                "contribution": round(adj, 2),
                "direction": "positive",
                "label": f"Founding team includes {int(exits)} prior exit(s)",
            }
        )

    years = fv["max_domain_years"]
    if years:
        adj = _clamp(years * 1.6, 0, 20)
        base += adj
        contributions.append(
            {
                "feature": "max_domain_years",
                "value": round(years, 1),
                "contribution": round(adj, 2),
                "direction": "positive",
                "label": f"{years:.0f} years of domain experience on the founding team",
            }
        )

    commits = fv["total_github_commits"]
    if commits:
        adj = _clamp(np.log1p(commits) * 2.6, 0, 14)
        base += adj
        contributions.append(
            {
                "feature": "total_github_commits",
                "value": int(commits),
                "contribution": round(adj, 2),
                "direction": "positive",
                "label": f"{int(commits)} public commits in the last 90 days",
            }
        )

    # Verifiability is itself a credibility signal: an unlinkable founder cannot
    # be independently checked, which is the whole premise of the platform.
    coverage = (fv["linkedin_coverage"] + fv["github_coverage"]) / 2
    adj = _clamp((coverage - 0.5) * 18.0, -9, 9)
    base += adj
    contributions.append(
        {
            "feature": "profile_coverage",
            "value": round(coverage, 2),
            "contribution": round(adj, 2),
            "direction": "positive" if adj >= 0 else "negative",
            "label": (
                f"{coverage:.0%} of founders have verifiable public profiles"
                + ("" if coverage >= 0.5 else " — limits independent verification")
            ),
        }
    )

    if fv["n_founders"] == 1:
        base -= 5
        contributions.append(
            {
                "feature": "n_founders",
                "value": 1,
                "contribution": -5.0,
                "direction": "negative",
                "label": "Solo founder — no co-founder redundancy",
            }
        )

    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return _clamp(base), contributions[:3], "rule_additive"


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _narrate(name: str, score: float, contribs: list[dict]) -> str:
    """Turn attributions into the plain-English rationale the report requires."""
    band = _band(score)
    if not contribs:
        return f"{name} is {band} ({score:.0f}/100). No dominant driver identified."
    lead = contribs[0]["label"]
    if len(contribs) > 1:
        return f"{name} is {band} ({score:.0f}/100). Primary driver: {lead}. Also weighing: {contribs[1]['label'].lower()}."
    return f"{name} is {band} ({score:.0f}/100). Primary driver: {lead}."


def compute_scores(
    db: Session,
    s: Startup,
    cohort_stats: dict | None = None,
    persist: bool = True,
    explained: tuple | None = None,
) -> Score:
    growth, growth_c, growth_m = _score_growth(s, explained)
    risk, risk_c, risk_m = _score_risk(s, cohort_stats)
    fraud, fraud_c, fraud_signals, fraud_m = _score_fraud(s)
    founder, founder_c, founder_m = _score_founder(s)

    # Fraud is inverted in the composite: a high fraud score must pull the
    # composite DOWN, while the other three push it up.
    composite = (
        COMPOSITE_WEIGHTS["growth_potential"] * growth
        + COMPOSITE_WEIGHTS["risk_level"] * risk
        + COMPOSITE_WEIGHTS["founder_credibility"] * founder
        + COMPOSITE_WEIGHTS["fraud_likelihood"] * (100.0 - fraud)
    )

    cohort_size = (cohort_stats or {}).get("cohort_size", 0)
    confidence = "high" if cohort_size >= settings.min_cohort_size else "low"

    score = Score(
        startup_id=s.startup_id,
        growth_potential_score=round(growth, 1),
        risk_level_score=round(risk, 1),
        fraud_likelihood_score=round(fraud, 1),
        founder_credibility_score=round(founder, 1),
        composite_score=round(_clamp(composite), 1),
        shap_top_features={
            "growth_potential": {"method": growth_m, "features": growth_c},
            "risk_level": {"method": risk_m, "features": risk_c},
            "fraud_likelihood": {"method": fraud_m, "features": fraud_c},
            "founder_credibility": {"method": founder_m, "features": founder_c},
        },
        rationale={
            "growth_potential": _narrate("Growth potential", growth, growth_c),
            "risk_level": _narrate("Risk profile", risk, risk_c),
            "fraud_likelihood": (
                f"Fraud likelihood is {'elevated' if fraud > 40 else 'low'} ({fraud:.0f}/100). "
                + (fraud_c[0]["label"] if fraud_c else "No anomalies detected.")
            ),
            "founder_credibility": _narrate("Founder credibility", founder, founder_c),
            "composite": (
                f"Composite {composite:.0f}/100 — weighted from growth ({growth:.0f}), "
                f"risk ({risk:.0f}), founder credibility ({founder:.0f}) and inverted "
                f"fraud likelihood ({fraud:.0f})."
                + (
                    ""
                    if confidence == "high"
                    else f" Peer cohort has only {cohort_size} comparable startups, "
                    f"below the {settings.min_cohort_size} needed for a confident "
                    "peer-relative read."
                )
            ),
        },
        confidence=confidence,
        cohort_size=cohort_size,
        model_version=(_load_growth() or {}).get("version", "heuristic-v1"),
    )

    if persist:
        # Retire the previous scores for this startup: the history stays, but
        # only one row is the one queries should see.
        db.query(Score).filter(
            Score.startup_id == s.startup_id, Score.is_current.is_(True)
        ).update({"is_current": False}, synchronize_session=False)
        db.add(score)
        for sig in fraud_signals:
            db.add(FraudSignal(startup_id=s.startup_id, **sig))
        db.flush()

    return score


def score_all(db: Session, batch_log_every: int = 500) -> int:
    """Score every startup. Cohort stats are computed once per sector+stage."""
    from collections import Counter

    startups = db.query(Startup).all()
    density = Counter((s.sector, s.stage) for s in startups)

    # Explaining a chunk at a time costs about what predicting alone does; one
    # row at a time would roughly double the run.
    bundle = _load_growth()
    explanations: dict[str, tuple | None] = {}
    if bundle:
        chunk = 500
        for start in range(0, len(startups), chunk):
            window = startups[start:start + chunk]
            results = explain.growth_explain_batch(bundle, [model_row(x) for x in window])
            explanations.update(zip((x.startup_id for x in window), results, strict=True))

    n = 0
    for s in startups:
        key = (s.sector, s.stage)
        compute_scores(
            db, s,
            cohort_stats={"cohort_size": density[key], "sector_density": density[key]},
            explained=explanations.get(s.startup_id),
        )
        n += 1
        if n % batch_log_every == 0:
            db.commit()
            print(f"    scored {n}/{len(startups)}")
    db.commit()
    return n
