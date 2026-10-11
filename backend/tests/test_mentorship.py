"""Mentorship offers, and who is allowed to see what."""

from __future__ import annotations

import uuid

import pytest

from app.models import MentorshipOffer, Startup, User


def _account(client, role: str, name: str):
    email = f"{role[:2]}{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={
        "email": email, "password": "correct-horse-9", "name": name, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["access_token"], r.json()["user"]["user_id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def scene(client, db):
    """A founder with one company, a would-be mentor, and an unrelated viewer."""
    founder, founder_id = _account(client, "founder", "Founder Anita")
    mentor, _ = _account(client, "investor", "Mentor Ravi")
    outsider, _ = _account(client, "investor", "Nosy Viewer")
    s = Startup(legal_name="Mentored Labs Private Limited", stage="seed", sector="FinTech",
                hq_city="Bengaluru", source="registration", owner_user_id=founder_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    yield {"founder": founder, "mentor": mentor, "outsider": outsider, "startup_id": s.startup_id}
    db.query(MentorshipOffer).filter(MentorshipOffer.startup_id == s.startup_id).delete()
    db.delete(s)
    db.query(User).filter(User.user_id == founder_id).delete()
    db.commit()


def _offer(client, scene, token=None):
    return client.post("/api/mentorship/offers", headers=_auth(token or scene["mentor"]), json={
        "startup_id": scene["startup_id"], "message": "I can help with pricing.",
        "focus_areas": ["Pricing"], "hours_per_month": 4})


def test_a_founder_cannot_mentor_their_own_company(client, scene):
    r = _offer(client, scene, token=scene["founder"])
    assert r.status_code == 422
    assert "own company" in r.json()["detail"]


def test_only_the_founder_reads_the_inbox(client, scene):
    assert _offer(client, scene).status_code == 201
    url = f"/api/mentorship/startups/{scene['startup_id']}/offers"
    assert client.get(url, headers=_auth(scene["outsider"])).status_code == 403
    assert client.get(url, headers=_auth(scene["mentor"])).status_code == 403
    mine = client.get(url, headers=_auth(scene["founder"]))
    assert mine.status_code == 200 and len(mine.json()) == 1


def test_an_offer_is_private_until_accepted_and_published(client, scene):
    """Three gates: offered, accepted-but-private, and public. Only the last
    one is visible to a stranger, and the pitch text never is."""
    offer_id = _offer(client, scene).json()["offer_id"]
    public = f"/api/mentorship/startups/{scene['startup_id']}/mentors"

    assert client.get(public).json()["mentors"] == []

    client.post(f"/api/mentorship/offers/{offer_id}/decide",
                headers=_auth(scene["founder"]), json={"accept": True, "public": False})
    assert client.get(public).json()["mentors"] == [], "a private acceptance must stay private"

    client.patch(f"/api/mentorship/offers/{offer_id}/visibility?public=true",
                 headers=_auth(scene["founder"]))
    mentors = client.get(public).json()["mentors"]
    assert len(mentors) == 1
    assert mentors[0]["mentor_name"] == "Mentor Ravi"
    # The private pitch and the mentor's contact details are not public.
    assert "message" not in mentors[0]
    assert "mentor_email" not in mentors[0]


def test_a_declined_offer_can_be_made_again_but_never_shows(client, scene):
    offer_id = _offer(client, scene).json()["offer_id"]
    client.post(f"/api/mentorship/offers/{offer_id}/decide",
                headers=_auth(scene["founder"]), json={"accept": False})
    public = f"/api/mentorship/startups/{scene['startup_id']}/mentors"
    assert client.get(public).json()["mentors"] == []
    # Declining is not a permanent ban; the mentor may try again.
    again = _offer(client, scene)
    assert again.status_code == 201 and again.json()["status"] == "offered"


def test_duplicate_live_offers_are_refused(client, scene):
    assert _offer(client, scene).status_code == 201
    assert _offer(client, scene).status_code == 409


def test_only_the_mentor_can_withdraw(client, scene):
    offer_id = _offer(client, scene).json()["offer_id"]
    assert client.delete(f"/api/mentorship/offers/{offer_id}",
                         headers=_auth(scene["outsider"])).status_code == 403
    assert client.delete(f"/api/mentorship/offers/{offer_id}",
                         headers=_auth(scene["mentor"])).status_code == 204
