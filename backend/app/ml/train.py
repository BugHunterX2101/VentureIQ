"""Train the growth-potential model on real YC outcome labels.

This mirrors the fused-LLM approach of Maarouf et al. (2025), which the report
cites: structured features concatenated with a text embedding of the company's
own description, into one classifier. We substitute TF-IDF + SVD for BERT ---
same shape, no 400MB download, and it trains in seconds on a laptop. Swapping in
a sentence-transformer later is a drop-in change to `_text_matrix`.

Label: YC `status`. Positive = Acquired / Public (a realised good outcome).
Negative = Inactive (dead). Active companies are EXCLUDED from training --- their
outcome has not resolved yet, and treating "still going" as either class would
poison the labels.

Run:  python -m app.ml.train
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.core.config import ARTIFACTS, DATA_RAW

MODEL_PATH = ARTIFACTS / "growth_model.joblib"
METRICS_PATH = ARTIFACTS / "growth_metrics.json"
FRAUD_MODEL_PATH = ARTIFACTS / "fraud_model.joblib"

NUMERIC = ["team_size", "company_age_years", "n_tags", "description_length", "is_top_company"]
CATEGORICAL = ["industry", "region_bucket", "stage_bucket"]


def _load_yc() -> list[dict[str, Any]]:
    path = DATA_RAW / "yc_companies_all.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing --- run the curl in data/raw/README.md first"
        )
    with path.open() as fh:
        return json.load(fh)


def _region_bucket(regions: list[str] | None, locations: str | None) -> str:
    blob = " ".join(regions or []) + " " + (locations or "")
    blob = blob.lower()
    for needle, bucket in [
        ("india", "India"), ("united states", "US"), ("america", "US"),
        ("united kingdom", "UK"), ("europe", "Europe"), ("canada", "Canada"),
        ("latin america", "LatAm"), ("africa", "Africa"), ("asia", "Asia"),
    ]:
        if needle in blob:
            return bucket
    return "Other"


def build_frame(companies: list[dict[str, Any]]) -> tuple[Any, np.ndarray, list[str]]:
    """Rows -> (feature DataFrame, label array, text corpus). Excludes Active."""
    import pandas as pd

    rows, labels, texts = [], [], []
    for c in companies:
        status = (c.get("status") or "").lower()
        if status not in {"acquired", "public", "inactive"}:
            continue  # Active == unresolved, see module docstring

        batch = c.get("batch") or ""
        year = None
        for tok in batch.split():
            if tok.isdigit():
                year = int(tok)
        age = (2026 - year) if year else 8.0

        desc = (c.get("long_description") or c.get("one_liner") or "").strip()
        team = c.get("team_size") or 0

        rows.append(
            {
                "team_size": float(team),
                "company_age_years": float(age),
                "n_tags": float(len(c.get("tags") or [])),
                "description_length": float(len(desc)),
                "is_top_company": 1.0 if c.get("top_company") else 0.0,
                "industry": (c.get("industry") or "Unknown")[:64],
                "region_bucket": _region_bucket(c.get("regions"), c.get("all_locations")),
                "stage_bucket": (c.get("stage") or "Unknown")[:32],
            }
        )
        labels.append(1 if status in {"acquired", "public"} else 0)
        texts.append(desc)

    return pd.DataFrame(rows), np.array(labels), texts


def _make_pipeline() -> Pipeline:
    """Structured branch + text branch, concatenated --- the 'fused' shape."""
    structured = ColumnTransformer(
        [
            (
                "num",
                Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]),
                NUMERIC,
            ),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", min_frequency=5),
                CATEGORICAL,
            ),
            (
                "text",
                Pipeline(
                    [
                        (
                            "tfidf",
                            TfidfVectorizer(
                                max_features=6000,
                                ngram_range=(1, 2),
                                min_df=3,
                                stop_words="english",
                                sublinear_tf=True,
                            ),
                        ),
                        # SVD stands in for the BERT document embedding in the
                        # cited paper: a dense, fixed-width semantic vector.
                        ("svd", TruncatedSVD(n_components=96, random_state=42)),
                    ]
                ),
                "description",
            ),
        ],
        remainder="drop",
    )
    return Pipeline(
        [
            ("features", structured),
            (
                "clf",
                GradientBoostingClassifier(
                    n_estimators=300, learning_rate=0.05, max_depth=3,
                    subsample=0.85, random_state=42,
                ),
            ),
        ]
    )


def train_growth_model(verbose: bool = True) -> dict[str, Any]:
    companies = _load_yc()
    X, y, texts = build_frame(companies)
    X["description"] = texts

    if verbose:
        print(f"  labelled rows: {len(X)}  (positive={int(y.sum())}, negative={int((1-y).sum())})")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.22, random_state=42, stratify=y
    )

    results: dict[str, dict[str, float]] = {}
    candidates = {
        "gradient_boosting": _make_pipeline(),
    }
    # Baselines, so the dissertation can report a comparison table rather than a
    # single unexplained number.
    lr = _make_pipeline()
    lr.set_params(clf=LogisticRegression(max_iter=2000, class_weight="balanced"))
    candidates["logistic_regression"] = lr
    rf = _make_pipeline()
    rf.set_params(
        clf=RandomForestClassifier(
            n_estimators=400, min_samples_leaf=2, class_weight="balanced_subsample",
            random_state=42, n_jobs=-1,
        )
    )
    candidates["random_forest"] = rf

    best_name, best_model, best_auc = None, None, -1.0
    for name, model in candidates.items():
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]
        pred = (proba >= 0.5).astype(int)
        m = {
            "accuracy": round(float(accuracy_score(y_test, pred)), 4),
            "balanced_accuracy": round(float(balanced_accuracy_score(y_test, pred)), 4),
            "precision": round(float(precision_score(y_test, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_test, pred, zero_division=0)), 4),
            "auroc": round(float(roc_auc_score(y_test, proba)), 4),
        }
        results[name] = m
        if verbose:
            print(f"  {name:22s} AUROC={m['auroc']:.4f}  bal_acc={m['balanced_accuracy']:.4f}")
        if m["auroc"] > best_auc:
            best_name, best_model, best_auc = name, model, m["auroc"]

    if verbose:
        print(f"\n  best: {best_name} (AUROC {best_auc:.4f})")
        print(
            classification_report(
                y_test, best_model.predict(X_test),
                target_names=["did not exit", "acquired/public"], zero_division=0,
            )
        )

    joblib.dump(
        {"model": best_model, "numeric": NUMERIC, "categorical": CATEGORICAL,
         "algo": best_name, "version": f"growth-{best_name}-v1"},
        MODEL_PATH,
    )

    metrics = {
        "trained_on": "Y Combinator companies (yc-oss/api), status label",
        "n_labelled": int(len(X)),
        "n_positive": int(y.sum()),
        "n_negative": int((1 - y).sum()),
        "positive_class": "acquired or public",
        "excluded": "Active companies (outcome unresolved)",
        "test_size": 0.22,
        "chosen_model": best_name,
        "comparison": results,
        "caveat": (
            "Trained on global YC data because no labelled Indian startup outcome "
            "dataset exists publicly (docs/BUILD_PLAN.md Problem 3). Applying this "
            "to Indian startups is a domain transfer and should be reported as such."
        ),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    if verbose:
        print(f"\n  saved model  -> {MODEL_PATH}")
        print(f"  saved metrics-> {METRICS_PATH}")
    return metrics


def train_fraud_model(verbose: bool = True) -> dict[str, Any]:
    """Unsupervised anomaly detector over financial ratios.

    Explicitly NOT a fraud classifier --- there is no labelled fraud data for
    Indian startups (or anywhere public). It learns the shape of 'normal' and
    flags outliers for human review, which is what the report's section 8.1.5
    actually describes.
    """
    from sklearn.ensemble import IsolationForest

    from app.core.database import SessionLocal
    from app.ml.features import financial_feature_matrix

    db = SessionLocal()
    try:
        matrix, ids, names = financial_feature_matrix(db)
    finally:
        db.close()

    if len(matrix) < 50:
        if verbose:
            print("  not enough rows to fit the anomaly detector; skipping")
        return {"trained": False, "reason": "insufficient rows"}

    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)

    iso = IsolationForest(
        n_estimators=250, contamination=0.06, random_state=42, n_jobs=-1
    )
    iso.fit(scaled)

    # PCA reconstruction error stands in for the report's TensorFlow
    # autoencoder: same "can the model rebuild this row?" signal, no TF dep.
    from sklearn.decomposition import PCA

    n_comp = max(2, min(6, scaled.shape[1] - 1))
    pca = PCA(n_components=n_comp, random_state=42).fit(scaled)
    recon = pca.inverse_transform(pca.transform(scaled))
    errors = np.mean((scaled - recon) ** 2, axis=1)

    joblib.dump(
        {
            "scaler": scaler, "isolation_forest": iso, "pca": pca,
            "feature_names": names,
            "recon_error_p95": float(np.percentile(errors, 95)),
            "recon_error_mean": float(errors.mean()),
            "recon_error_std": float(errors.std() or 1.0),
            "version": "fraud-iforest-pca-v1",
        },
        FRAUD_MODEL_PATH,
    )

    out = {
        "trained": True,
        "n_rows": int(len(matrix)),
        "n_features": int(scaled.shape[1]),
        "features": names,
        "contamination": 0.06,
        "flagged": int((iso.predict(scaled) == -1).sum()),
        "recon_error_p95": float(np.percentile(errors, 95)),
    }
    if verbose:
        print(f"  fitted on {out['n_rows']} rows x {out['n_features']} features")
        print(f"  flagged {out['flagged']} as anomalous at 6% contamination")
        print(f"  saved -> {FRAUD_MODEL_PATH}")
    return out


if __name__ == "__main__":
    print("\n=== Growth potential model ===")
    train_growth_model()
    print("\n=== Fraud / anomaly detector ===")
    train_fraud_model()
    print()
