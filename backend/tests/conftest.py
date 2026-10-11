"""Test fixtures.

Every test runs against a throwaway SQLite database in a temp directory, so a
test run can never touch backend/ventureiq.db. Tests that need the network or
the imported MCA registry are marked and can be deselected:

    pytest                     # everything available here
    pytest -m "not network"    # offline only
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="viq-tests-")
os.environ["VIQ_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ.setdefault("VIQ_JWT_SECRET", "test-secret-not-used-anywhere-else")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Score, Startup  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    # As a context manager TestClient keeps one event loop alive for the whole
    # test. Without it, each request gets a fresh portal and the agent's
    # background research task is cancelled the moment the request returns.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def startup(db):
    """One scored company to hang tests off."""
    s = Startup(legal_name="Testco Labs Private Limited", stage="seed", sector="HealthTech",
                hq_city="Bengaluru", hq_state="Karnataka", source="registration", verified=False)
    db.add(s)
    db.flush()
    db.add(Score(startup_id=s.startup_id, growth_potential_score=70, risk_level_score=60,
                 fraud_likelihood_score=10, founder_credibility_score=55, composite_score=64.2,
                 confidence="medium", model_version="test"))
    db.commit()
    db.refresh(s)
    yield s
    db.delete(s)
    db.commit()


@pytest.fixture
def account(client):
    """A registered investor with a token, unique per test."""
    import uuid

    email = f"t{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={
        "email": email, "password": "correct-horse-9", "name": "Test Investor", "role": "investor"})
    assert r.status_code == 201, r.text
    body = r.json()
    return {
        "email": email,
        "token": body["access_token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


@pytest.fixture
def founder(client):
    import uuid

    email = f"f{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={
        "email": email, "password": "correct-horse-9", "name": "Test Founder", "role": "founder"})
    assert r.status_code == 201, r.text
    body = r.json()
    return {"email": email, "user": body["user"],
            "headers": {"Authorization": f"Bearer {body['access_token']}"}}


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return Path(__file__).parent / "samples"
