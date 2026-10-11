"""SHAP attributions for the two trained models (report section 8.3).

Both models this project trains are tree ensembles, so both get exact Shapley
values from `shap.TreeExplainer` --- no sampling, no surrogate model.

Two honest caveats, because the report's single phrase "SHAP rationale" hides
them (docs/BUILD_PLAN.md Problem 6 is about exactly this):

1. *Units.* SHAP decomposes what the model outputs, which is not what the UI
   shows. The growth classifier's values are additive in **log-odds** and the
   isolation forest's in **isolation path length**; the screen shows points on a
   0--100 score. Each attribution therefore carries the raw `shap_value` in the
   model's own units, and a `contribution` in score points obtained by splitting
   the model's total move across features in proportion to their Shapley share.
   The split is exact in aggregate and monotone per feature; it is not itself a
   Shapley value in score space, and nothing here claims it is.
2. *Coverage.* Only these two scores have a model to explain. Risk and founder
   credibility are additive rule compositions whose terms are already their own
   explanation, and they keep reporting those terms with `method="rules"`.

The 96 SVD dimensions of the description are summed back into one `description`
attribution: an individual latent dimension means nothing to a reader, and the
sum over a group of features is still a valid Shapley value for that group.
"""

from __future__ import annotations

import re
import threading
from typing import Any

import numpy as np

from app.core.config import settings

# Populated on first use; TreeExplainer construction is the expensive part.
_explainers: dict[int, Any] = {}
_lock = threading.Lock()
_shap_unavailable = False


def available() -> bool:
    """False if `shap` is switched off or missing, so callers fall back.

    The import is deliberately deferred to the first attribution rather than
    done at module load: it costs ~200 MB of resident memory, and a deployment
    that never explains anything should never pay it.
    """
    global _shap_unavailable
    if _shap_unavailable or not settings.enable_shap:
        return False
    try:
        import shap  # noqa: F401, PLC0415
    except Exception:
        _shap_unavailable = True
        return False
    return True


def _explainer(model: Any) -> Any | None:
    """One cached TreeExplainer per model object."""
    if not available():
        return None
    key = id(model)
    with _lock:
        if key not in _explainers:
            import shap  # noqa: PLC0415

            try:
                _explainers[key] = shap.TreeExplainer(model)
            except Exception:
                _explainers[key] = None
        return _explainers[key]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------------
# growth: gradient boosting over numeric + one-hot + SVD(description)
# --------------------------------------------------------------------------

# ColumnTransformer names its outputs "<block>__<feature>"; map each back to the
# column a reader would recognise.
_NUMERIC_LABEL = {
    "team_size": "Team size",
    "company_age_years": "Company age",
    "n_tags": "Number of tags",
    "description_length": "Description length",
    "is_top_company": "Flagged a top company",
}


def _group_of(name: str) -> tuple[str, str | None]:
    """'cat__industry_FinTech' -> ('industry', 'FinTech'); SVD dims -> description."""
    block, _, rest = name.partition("__")
    if block == "text":
        return "description", None
    if block == "num":
        return rest, None
    if block == "cat":
        for column in ("industry", "region_bucket", "stage_bucket"):
            if rest.startswith(column + "_"):
                return column, rest[len(column) + 1:]
        return rest, None
    return re.sub(r"^.*__", "", name), None


def _growth_label(group: str, level: str | None, row: dict[str, Any], points: float) -> str:
    direction = "raises" if points > 0 else "lowers"
    if group == "description":
        return f"What the company says it does {direction} the model's estimate"
    if group == "industry":
        return f"Operating in {level or row.get('industry', 'this sector')} {direction} it"
    if group == "region_bucket":
        return f"Being based in {level or row.get('region_bucket', 'this region')} {direction} it"
    if group == "stage_bucket":
        return f"Being at {level or row.get('stage_bucket', 'this')} stage {direction} it"
    value = row.get(group)
    if group == "team_size":
        if not value:
            return f"Having no headcount on file {direction} it"
        return f"A team of {value:,.0f} {direction} it"
    if group == "company_age_years":
        return f"Being {value:.1f} years old {direction} it"
    if group == "description_length":
        return f"A {value:,.0f}-character description {direction} it"
    label = _NUMERIC_LABEL.get(group, group.replace("_", " "))
    return f"{label} {direction} it"


def growth_explain_batch(
    bundle: dict[str, Any], rows: list[dict[str, Any]], top_k: int = 3
) -> list[tuple[float, list[dict[str, Any]], float] | None]:
    """`growth_explain` over many rows, transformed and explained in one call.

    Scoring the whole corpus one row at a time doubles the run, because both
    the TF-IDF/SVD transform and the tree traversal are far cheaper per row in
    bulk. Results come back aligned with `rows`.
    """
    if not rows:
        return []
    pipeline = bundle.get("model")
    if pipeline is None or not available():
        return [None] * len(rows)
    try:
        import pandas as pd  # noqa: PLC0415

        features = pipeline.named_steps["features"]
        clf = pipeline.named_steps["clf"]
        explainer = _explainer(clf)
        if explainer is None:
            return [None] * len(rows)

        matrix = features.transform(pd.DataFrame(rows))
        matrix = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
        probas = clf.predict_proba(matrix)[:, 1]
        values = np.asarray(explainer.shap_values(matrix))
        names = list(features.get_feature_names_out())
        base_proba = _sigmoid(float(np.ravel(explainer.expected_value)[0]))
    except Exception:
        return [None] * len(rows)

    out: list[tuple[float, list[dict[str, Any]], float] | None] = []
    for i, row in enumerate(rows):
        try:
            attributions = _assemble(
                names, np.ravel(values[i]), row, (float(probas[i]) - base_proba) * 100.0, top_k
            )
        except Exception:
            attributions = None
        out.append(
            None if attributions is None
            else (float(probas[i]), attributions, base_proba * 100.0)
        )
    return out


def growth_explain(
    bundle: dict[str, Any], row: dict[str, Any], top_k: int = 3
) -> tuple[float, list[dict[str, Any]], float] | None:
    """Predict and decompose in one pass.

    Returns (probability, attributions, base_rate_pct), where base_rate_pct is
    the model's average prediction --- the point the contributions move away
    from --- or None if SHAP is unavailable or the model isn't a tree ensemble.

    The prediction is taken from the transformed matrix rather than from the
    pipeline, because transforming a row means running TF-IDF and the SVD over
    the description; doing that once for both the prediction and the
    explanation is what keeps scoring the full corpus cheap.
    """
    pipeline = bundle.get("model")
    if pipeline is None or not available():
        return None
    try:
        import pandas as pd  # noqa: PLC0415

        features = pipeline.named_steps["features"]
        clf = pipeline.named_steps["clf"]
        explainer = _explainer(clf)
        if explainer is None:
            return None

        matrix = features.transform(pd.DataFrame([row]))
        matrix = matrix.toarray() if hasattr(matrix, "toarray") else np.asarray(matrix)
        proba = float(clf.predict_proba(matrix)[0, 1])
        values = np.ravel(explainer.shap_values(matrix))
        names = list(features.get_feature_names_out())
        if len(values) != len(names):
            return None

        base_proba = _sigmoid(float(np.ravel(explainer.expected_value)[0]))
        # The whole move this prediction makes away from the model's average,
        # expressed on the 0-100 scale the UI draws.
        attributions = _assemble(names, values, row, (proba - base_proba) * 100.0, top_k)
        if attributions is None:
            return None
        return proba, attributions, base_proba * 100.0
    except Exception:
        return None


def _assemble(
    names: list[str],
    values: np.ndarray,
    row: dict[str, Any],
    total_points: float,
    top_k: int,
) -> list[dict[str, Any]] | None:
    """Group raw per-column Shapley values into readable, signed attributions."""
    if len(values) != len(names):
        return None

    grouped: dict[str, dict[str, Any]] = {}
    for name, value in zip(names, values, strict=True):
        group, level = _group_of(name)
        entry = grouped.setdefault(group, {"shap": 0.0, "level": None})
        entry["shap"] += float(value)
        # For a one-hot block, the level that is actually set carries the mass.
        if level is not None and abs(float(value)) > abs(entry.get("level_shap", 0.0)):
            entry["level"], entry["level_shap"] = level, float(value)

    # Shapley values sum to (logit(p) - base logit), which always agrees in sign
    # with `total_points` because the logit is monotone in the probability.
    # Splitting by signed share therefore keeps every feature's direction intact
    # and makes the parts sum to the whole exactly.
    net = sum(e["shap"] for e in grouped.values())
    gross = sum(abs(e["shap"]) for e in grouped.values())
    # When the pushes cancel out, the ratio explodes and the split stops meaning
    # anything; report no attribution rather than a wild one.
    if gross < 1e-12 or abs(net) < 0.05 * gross:
        return None

    out: list[dict[str, Any]] = []
    for group, entry in grouped.items():
        points = total_points * (entry["shap"] / net)
        if abs(points) < 0.05:
            continue
        out.append({
            "feature": group,
            "value": entry["level"] if entry["level"] is not None else row.get(group),
            "contribution": round(points, 2),
            "shap_value": round(entry["shap"], 4),
            "direction": "positive" if points > 0 else "negative",
            "label": _growth_label(group, entry["level"], row, points),
        })
    out.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return out[:top_k]


# --------------------------------------------------------------------------
# fraud: isolation forest over financial ratios
# --------------------------------------------------------------------------

_FRAUD_LABEL = {
    "revenue": "reported revenue",
    "burn_rate_monthly": "monthly burn",
    "cash_balance": "cash balance",
    "runway_months": "runway",
    "revenue_growth_pct": "revenue growth",
    "gross_margin_pct": "gross margin",
    "ltv_cac_ratio": "LTV:CAC ratio",
    "revenue_per_head": "revenue per employee",
    "burn_multiple": "burn multiple",
    "sam_tam_ratio": "SAM:TAM ratio",
}


def fraud_attributions(
    bundle: dict[str, Any], scaled_row: np.ndarray, total_points: float, top_k: int = 3
) -> list[dict[str, Any]] | None:
    """Which financial ratios made this profile isolate as an outlier.

    TreeExplainer on an isolation forest decomposes the sample's *path length*:
    a negative value is a feature that made the row easier to isolate, which is
    what "anomalous" means. Those are the only ones worth showing, so the split
    of `total_points` runs over them.
    """
    iso = bundle.get("isolation_forest")
    raw_values = bundle.get("feature_names") or []
    if iso is None or not available() or total_points <= 0:
        return None
    try:
        explainer = _explainer(iso)
        if explainer is None:
            return None
        values = np.ravel(explainer.shap_values(scaled_row))
        if len(values) != len(raw_values):
            return None

        # Shorter path (negative) == more isolating == what we attribute.
        isolating = {n: -float(v) for n, v in zip(raw_values, values, strict=True) if v < 0}
        denominator = sum(isolating.values())
        if denominator < 1e-12:
            return None

        out = [
            {
                "feature": name,
                "value": None,
                "contribution": round(total_points * weight / denominator, 2),
                "shap_value": round(-weight, 4),
                "direction": "negative",
                "label": (
                    f"Its {_FRAUD_LABEL.get(name, name.replace('_', ' '))} is what "
                    f"separates this profile from normal ones"
                ),
            }
            for name, weight in sorted(isolating.items(), key=lambda kv: -kv[1])[:top_k]
        ]
        return [c for c in out if abs(c["contribution"]) >= 0.05] or None
    except Exception:
        return None
