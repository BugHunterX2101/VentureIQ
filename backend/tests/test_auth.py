"""Accounts, sessions and the boundary between them."""

import pytest


class TestRegistration:
    def test_investor_signup_creates_an_investor_profile(self, client, account):
        assert account["user"]["role"] == "investor"
        assert account["user"]["investor_id"], "an investor account owns an investor row"
        assert account["user"]["has_mandate"] is False

    def test_founder_signup_has_no_investor(self, founder):
        assert founder["user"]["role"] == "founder"
        assert founder["user"]["investor_id"] is None

    def test_duplicate_email_is_refused(self, client, account):
        r = client.post("/api/auth/register", json={
            "email": account["email"], "password": "correct-horse-9", "name": "Impostor", "role": "investor"})
        assert r.status_code == 409

    @pytest.mark.parametrize("password", ["short", "1234567"])
    def test_short_passwords_are_refused(self, client, password):
        r = client.post("/api/auth/register", json={
            "email": "x@example.com", "password": password, "name": "X Y", "role": "investor"})
        assert r.status_code == 422

    def test_password_is_never_stored_or_returned(self, client, account, db):
        from app.models import User

        user = db.query(User).filter(User.email == account["email"]).first()
        assert user.password_hash and "correct-horse-9" not in user.password_hash
        assert "password" not in client.get("/api/auth/me", headers=account["headers"]).json()


class TestSignIn:
    def test_login_round_trip(self, client, account):
        r = client.post("/api/auth/login", json={"email": account["email"], "password": "correct-horse-9"})
        assert r.status_code == 200 and r.json()["access_token"]

    def test_email_is_case_insensitive(self, client, account):
        r = client.post("/api/auth/login", json={"email": account["email"].upper(), "password": "correct-horse-9"})
        assert r.status_code == 200

    def test_wrong_password_is_refused(self, client, account):
        r = client.post("/api/auth/login", json={"email": account["email"], "password": "nope"})
        assert r.status_code == 401

    def test_repeated_wrong_passwords_are_throttled(self, client, account):
        """Guessing a password should get expensive, not stay free."""
        from app.core import security

        security.clear_failed_logins(f"email:{account['email']}", "ip:testclient")
        codes = [
            client.post("/api/auth/login",
                        json={"email": account["email"], "password": f"wrong-{i}"}).status_code
            for i in range(security._MAX_ATTEMPTS + 2)
        ]
        assert codes[0] == 401
        assert 429 in codes, "unlimited password guesses are allowed"
        # The right password is refused too while the block stands.
        blocked = client.post("/api/auth/login",
                              json={"email": account["email"], "password": "correct-horse-9"})
        assert blocked.status_code == 429
        assert blocked.headers.get("Retry-After")

        security.clear_failed_logins(f"email:{account['email']}", "ip:testclient")
        assert client.post("/api/auth/login",
                           json={"email": account["email"], "password": "correct-horse-9"}
                           ).status_code == 200

    def test_unknown_account_gives_the_same_answer(self, client):
        """Login must not reveal which emails exist."""
        r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope"})
        assert r.status_code == 401

    @pytest.mark.parametrize("header", [None, "Bearer nonsense", "Basic abc", "Bearer "])
    def test_me_requires_a_real_token(self, client, header):
        headers = {"Authorization": header} if header else {}
        assert client.get("/api/auth/me", headers=headers).status_code == 401


class TestOwnership:
    def test_cannot_read_another_investors_feed(self, client, account, db):
        from app.models import Investor

        other = Investor(name="Someone Else", investor_type="angel")
        db.add(other)
        db.commit()
        r = client.get(f"/api/investors/{other.investor_id}/feed", headers=account["headers"])
        assert r.status_code == 403
        db.delete(other)
        db.commit()

    def test_cannot_write_to_another_investors_events(self, client, account, startup, db):
        from app.models import Investor

        other = Investor(name="Someone Else", investor_type="angel")
        db.add(other)
        db.commit()
        r = client.post("/api/events", headers=account["headers"], json={
            "investor_id": other.investor_id, "startup_id": startup.startup_id, "event_type": "view"})
        assert r.status_code == 403
        db.delete(other)
        db.commit()

    def test_anonymous_events_are_refused(self, client, account, startup):
        r = client.post("/api/events", json={
            "investor_id": account["user"]["investor_id"], "startup_id": startup.startup_id,
            "event_type": "view"})
        assert r.status_code == 401

    def test_founders_only_see_their_own_companies(self, client, founder, startup, db):
        startup.owner_user_id = founder["user"]["user_id"]
        db.commit()
        mine = client.get("/api/auth/me/startups", headers=founder["headers"]).json()
        assert [s["startup_id"] for s in mine] == [startup.startup_id]

        other = client.post("/api/auth/register", json={
            "email": "other-founder@example.com", "password": "correct-horse-9",
            "name": "Other", "role": "founder"}).json()
        theirs = client.get("/api/auth/me/startups",
                            headers={"Authorization": f"Bearer {other['access_token']}"}).json()
        assert theirs == []


class TestWatchlist:
    def test_save_note_and_remove(self, client, account, startup):
        h = account["headers"]
        r = client.post("/api/auth/me/watchlist", headers=h,
                        json={"startup_id": startup.startup_id, "note": "strong team"})
        assert r.status_code == 201
        assert r.json()["startup"]["legal_name"] == startup.legal_name

        items = client.get("/api/auth/me/watchlist", headers=h).json()
        assert len(items) == 1 and items[0]["note"] == "strong team"
        assert client.get("/api/auth/me", headers=h).json()["watchlist_count"] == 1

        moved = client.patch(f"/api/auth/me/watchlist/{startup.startup_id}", headers=h,
                             json={"startup_id": startup.startup_id, "stage": "contacted"})
        assert moved.json()["stage"] == "contacted"

        assert client.delete(f"/api/auth/me/watchlist/{startup.startup_id}", headers=h).status_code == 204
        assert client.get("/api/auth/me/watchlist", headers=h).json() == []

    def test_saving_twice_does_not_duplicate(self, client, account, startup):
        h = account["headers"]
        client.post("/api/auth/me/watchlist", headers=h, json={"startup_id": startup.startup_id})
        client.post("/api/auth/me/watchlist", headers=h, json={"startup_id": startup.startup_id, "note": "again"})
        items = client.get("/api/auth/me/watchlist", headers=h).json()
        assert len(items) == 1 and items[0]["note"] == "again"

    def test_unknown_startup_is_refused(self, client, account):
        r = client.post("/api/auth/me/watchlist", headers=account["headers"],
                        json={"startup_id": "does-not-exist"})
        assert r.status_code == 404

    def test_watchlist_needs_a_session(self, client):
        assert client.get("/api/auth/me/watchlist").status_code == 401


class TestGoogleOAuth:
    def test_providers_are_advertised(self, client):
        assert client.get("/api/auth/providers").json()["password"] is True

    def test_forged_state_never_signs_anyone_in(self, client):
        r = client.get("/api/auth/google/callback?state=forged&code=x", follow_redirects=False)
        # Either not configured here, or bounced back to the login page.
        assert r.status_code in (303, 503)
        if r.status_code == 303:
            assert "error=expired_state" in r.headers["location"]
