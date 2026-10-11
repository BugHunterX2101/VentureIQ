"""Scoring: SHAP attributions, and one current score row per startup."""

from __future__ import annotations

import datetime as dt

import pytest

from app.ml import explain
from app.ml.scoring import _load_growth, compute_scores
from app.models import Score, Startup, StartupFinancials

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _company(db, **kw):
    s = Startup(legal_name=kw.pop("name", "Attribution Labs Private Limited"),
                stage="seed", sector="FinTech", hq_city="Bengaluru", hq_state="Karnataka",
                source="registration", employee_count=24, founded_date=dt.date(2019, 4, 1),
                one_liner="Payments infrastructure for small merchants", **kw)
    db.add(s)
    db.flush()
    db.add(StartupFinancials(startup_id=s.startup_id, revenue=4_000_000, burn_rate_monthly=250_000,
                             cash_balance=6_000_000, prior_year_revenue=2_200_000,
                             cac=900, ltv=3_400, tam_usd=2_000_000_000, sam_usd=250_000_000))
    db.commit()
    db.refresh(s)
    return s


def test_growth_attributions_are_shapley_when_the_model_is_loaded(db):
    """With shap and a trained model present, the method says so and the
    features are real columns rather than one opaque probability."""
    s = _company(db)
    try:
        score = compute_scores(db, s, persist=False)
        block = score.shap_top_features["growth_potential"]

        if not (_load_growth() and explain.available()):
            pytest.skip("no trained growth model or shap on this machine")

        assert block["method"].startswith("shap:")
        named = [f for f in block["features"] if f["feature"] != "ml_exit_probability"]
        assert named, "SHAP produced no per-feature attributions"
        # Every attribution states its direction consistently with its sign.
        for f in named:
            if f.get("shap_value") is not None:
                assert (f["contribution"] > 0) == (f["direction"] == "positive")
        # The headline line carries no weight of its own; it summarises.
        headline = [f for f in block["features"] if f["feature"] == "ml_exit_probability"]
        assert headline and headline[0]["contribution"] == 0.0
    finally:
        db.delete(s)
        db.commit()


def test_scoring_twice_leaves_exactly_one_current_row(db):
    """Scores are appended for history, but only one row may be current --- SQL
    that joins the table would otherwise count a rescored startup twice."""
    s = _company(db, name="Rescored Labs Private Limited")
    try:
        compute_scores(db, s)
        compute_scores(db, s)
        db.commit()

        rows = db.query(Score).filter(Score.startup_id == s.startup_id).all()
        assert len(rows) == 2, "history should be kept"
        current = [r for r in rows if r.is_current]
        assert len(current) == 1
        assert s.latest_score.score_id == current[0].score_id
    finally:
        db.delete(s)  # cascades to its score rows
        db.commit()


def test_scoring_falls_back_when_shap_is_missing(db, monkeypatch):
    """Without shap installed the scorer still works; it just reports the
    prediction instead of decomposing it."""
    s = _company(db, name="Fallback Labs Private Limited")
    try:
        monkeypatch.setattr(explain, "_shap_unavailable", True)
        score = compute_scores(db, s, persist=False)
        block = score.shap_top_features["growth_potential"]
        assert not block["method"].startswith("shap:")
        assert 0 <= score.growth_potential_score <= 100
    finally:
        db.delete(s)
        db.commit()
