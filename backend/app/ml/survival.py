"""Company survival model, trained on India's own company register.

Why this exists: the growth model learns from 1,896 labelled Y Combinator
companies --- global, tiny, and a domain transfer when applied to an Indian
startup (docs/BUILD_PLAN.md Problem 3). The MCA master data already imported
into `registry.db` carries an outcome for **3.58 million Indian companies**:
the Registrar's own status. Roughly 987,000 of them have been struck off or
wound up. That is a real, officially published label, at a scale the YC set
cannot approach, on exactly the population this project is about.

What it predicts, stated precisely: **the probability that a company of this
shape has been struck off or dissolved rather than remaining on the register.**
That is corporate mortality, not startup failure. Most struck-off companies are
small entities removed for not filing returns, not failed venture-backed
startups. It belongs in the risk score as one signal among several, and it is
labelled as such wherever it surfaces.

Two honest limits, both measured in `survival_metrics.json` rather than waved at:

1. *Age is confounded with the label.* A company incorporated in 2005 has had
   twenty years in which to be struck off; one incorporated last year has had
   one. Age is kept as a feature because it genuinely carries risk, and the
   metrics report AUROC **within age bands** so a reader can see the model is
   not merely reading a clock.
2. *This is a snapshot, not a survival curve.* The register says what a company
   is today, not when it changed. A proper hazard model needs the date of
   strike-off, which the bulk data does not carry.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.core.config import ARTIFACTS, settings

MODEL_PATH = ARTIFACTS / "survival_model.joblib"
METRICS_PATH = ARTIFACTS / "survival_metrics.json"

# The Registrar's own vocabulary, split into an outcome we can learn from.
DISSOLVED = ("Strike Off", "Dissolved (Liquidated)", "Under Liquidation",
             "Under process of striking off")
ALIVE = ("Active",)
# Everything else --- amalgamated, converted to LLP, dormant --- is a corporate
# action or an ambiguous state, not a death. Training on it would teach the
# model that a successful merger looks like a failure.

NUMERIC = ["age_years", "log_paidup", "log_authorized", "capital_ratio", "capital_missing"]
CATEGORICAL = ["state", "company_class", "category", "industry"]
FEATURES = NUMERIC + CATEGORICAL


def _rows(db_path: Path, limit: int | None) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        sql = f"""
            SELECT registered, paidup_capital, authorized_capital, state, class,
                   category, industry, status
            FROM company
            WHERE registered IS NOT NULL
              AND status IN ({','.join('?' * (len(DISSOLVED) + len(ALIVE)))})
        """
        args: list[Any] = [*DISSOLVED, *ALIVE]
        if limit:
            # Deterministic thinning that keeps the natural class balance,
            # rather than ORDER BY RANDOM() over three million rows.
            sql += " AND (rowid % ?) = 0"
            args.append(max(1, _stride(conn, limit)))
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _stride(conn: sqlite3.Connection, limit: int) -> int:
    total = conn.execute(
        f"SELECT COUNT(*) FROM company WHERE registered IS NOT NULL AND status IN "
        f"({','.join('?' * (len(DISSOLVED) + len(ALIVE)))})", (*DISSOLVED, *ALIVE)
    ).fetchone()[0]
    return max(1, round(total / limit))


def build_frame(rows: list[tuple]):
    """Registry rows → the feature frame and the label."""
    import pandas as pd

    today = date.today()
    records, labels = [], []
    for registered, paidup, authorized, state, cls, category, industry, status in rows:
        try:
            year, month, day = (int(p) for p in registered[:10].split("-"))
            incorporated = date(year, month, day)
        except (ValueError, AttributeError):
            continue
        age = (today - incorporated).days / 365.25
        if not 0 <= age <= 125:
            continue
        paid = float(paidup or 0.0)
        auth = float(authorized or 0.0)
        records.append({
            "age_years": age,
            "log_paidup": float(np.log1p(max(paid, 0.0))),
            "log_authorized": float(np.log1p(max(auth, 0.0))),
            # A company that never called up the capital it was allowed to
            # issue is a different animal from one that issued all of it.
            "capital_ratio": float(paid / auth) if auth > 0 else 0.0,
            "capital_missing": 0.0 if auth > 0 else 1.0,
            "state": (state or "Unknown")[:48],
            "company_class": (cls or "Unknown")[:32],
            "category": (category or "Unknown")[:48],
            "industry": (industry or "Unknown")[:64],
        })
        labels.append(1 if status in DISSOLVED else 0)

    frame = pd.DataFrame.from_records(records)
    for col in CATEGORICAL:
        frame[col] = frame[col].astype("category")
    return frame, np.array(labels)


def _model():
    from sklearn.ensemble import HistGradientBoostingClassifier

    # Histogram boosting handles millions of rows and native categoricals
    # without one-hot blowing the feature space up to thousands of columns.
    return HistGradientBoostingClassifier(
        max_iter=250,
        learning_rate=0.08,
        max_depth=6,
        l2_regularization=1.0,
        categorical_features=[FEATURES.index(c) for c in CATEGORICAL],
        random_state=42,
    )


def train(limit: int | None = 1_200_000, verbose: bool = True) -> dict[str, Any]:
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from sklearn.model_selection import train_test_split

    db_path = Path(settings.registry_db_path)
    if not db_path.exists():
        return {"trained": False, "reason": "registry.db not imported"}

    rows = _rows(db_path, limit)
    if len(rows) < 10_000:
        return {"trained": False, "reason": f"only {len(rows)} usable rows"}
    X, y = build_frame(rows)
    if verbose:
        print(f"  {len(X):,} companies · {y.mean():.1%} struck off or dissolved")

    X_train, X_test, y_train, y_test = train_test_split(
        X[FEATURES], y, test_size=0.2, random_state=42, stratify=y
    )
    model = _model()
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]

    auroc = float(roc_auc_score(y_test, proba))
    brier = float(brier_score_loss(y_test, proba))

    # Does it know anything beyond "old companies die"? Score inside age bands,
    # where age barely varies, and see whether it still separates.
    bands: list[dict[str, Any]] = []
    ages = X_test["age_years"].to_numpy()
    for low, high in ((0, 3), (3, 7), (7, 12), (12, 20), (20, 125)):
        mask = (ages >= low) & (ages < high)
        if mask.sum() < 500 or len(set(y_test[mask])) < 2:
            continue
        bands.append({
            "age_band": f"{low}-{high}y",
            "n": int(mask.sum()),
            "dissolved_rate": round(float(y_test[mask].mean()), 4),
            "auroc": round(float(roc_auc_score(y_test[mask], proba[mask])), 4),
        })

    # A no-skill baseline that only knows age, for comparison.
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    age_only = LogisticRegression(max_iter=500)
    scaler = StandardScaler().fit(X_train[["age_years"]])
    age_only.fit(scaler.transform(X_train[["age_years"]]), y_train)
    age_auroc = float(roc_auc_score(
        y_test, age_only.predict_proba(scaler.transform(X_test[["age_years"]]))[:, 1]))

    metrics = {
        "trained": True,
        "n_companies": int(len(X)),
        "n_dissolved": int(y.sum()),
        "dissolved_rate": round(float(y.mean()), 4),
        "auroc": round(auroc, 4),
        "auroc_age_only_baseline": round(age_auroc, 4),
        "brier": round(brier, 4),
        "by_age_band": bands,
        "features": FEATURES,
        "source": "MCA Company Master Data (data.gov.in, GODL-India)",
        "predicts": ("Probability a company of this shape has been struck off or dissolved "
                     "rather than remaining on the register. Corporate mortality, not "
                     "startup failure."),
        "version": "survival-histgb-v1",
    }
    joblib.dump({"model": model, "features": FEATURES, "metrics": metrics,
                 "version": metrics["version"]}, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    if verbose:
        print(f"  AUROC {auroc:.4f} (age-only baseline {age_auroc:.4f}) · Brier {brier:.4f}")
        for b in bands:
            print(f"    {b['age_band']:>8}  n={b['n']:>7,}  base={b['dissolved_rate']:.1%}"
                  f"  AUROC {b['auroc']:.4f}")
        print(f"  saved -> {MODEL_PATH}")
    return metrics


_bundle: dict[str, Any] | None = None


def bundle() -> dict[str, Any] | None:
    global _bundle
    if _bundle is None and MODEL_PATH.exists():
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


def predict(record: dict[str, Any]) -> float | None:
    """Dissolution probability for one registry record, or None if unavailable."""
    b = bundle()
    if not b or not record.get("registered"):
        return None
    try:
        import pandas as pd

        X, _ = build_frame([(
            record.get("registered"), record.get("paidup_capital"),
            record.get("authorized_capital"), record.get("state"),
            record.get("class"), record.get("category"), record.get("industry"),
            "Active",  # label is ignored here; only the features are used
        )])
        if X.empty:
            return None
        return float(b["model"].predict_proba(pd.DataFrame(X[b["features"]]))[0, 1])
    except Exception:
        return None
