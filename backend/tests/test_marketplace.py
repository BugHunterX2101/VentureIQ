"""Marketplace listing rules."""

from __future__ import annotations

import uuid

from app.models import Listing, Startup, User


def _founder(client):
    email = f"f{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={
        "email": email, "password": "correct-horse-9", "name": "Test Founder", "role": "founder"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"], r.json()["user"]["user_id"]


def test_a_company_cannot_be_listed_twice_at_once(client, db):
    """Two open listings would offer the same equity twice over."""
    token, user_id = _founder(client)
    s = Startup(legal_name="Listed Twice Private Limited", stage="seed", sector="FinTech",
                hq_city="Bengaluru", source="registration", verified=True, owner_user_id=user_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    try:
        url = (f"/api/marketplace/listings?startup_id={s.startup_id}"
               "&ask_amount=200000&equity_offered_pct=2&rofr_days=0")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post(url, headers=headers).status_code == 201
        second = client.post(url, headers=headers)
        assert second.status_code == 409, second.text
        assert "already listed" in second.json()["detail"].lower()
        assert db.query(Listing).filter(Listing.startup_id == s.startup_id).count() == 1
    finally:
        db.query(Listing).filter(Listing.startup_id == s.startup_id).delete()
        db.delete(s)
        db.query(User).filter(User.user_id == user_id).delete()
        db.commit()
