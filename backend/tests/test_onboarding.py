"""The agentic registration flow, end to end.

Marked `network` because the agent really does fetch the company's website,
RDAP, DNS and GitHub. Run the offline subset with `pytest -m "not network"`.
"""

import time

import pytest

pytestmark = pytest.mark.network


def run_agent(client, payload, headers=None, timeout=90):
    """Start a session and wait for the agent to finish.

    This polls rather than reading the SSE stream: TestClient runs the app on a
    portal thread, and blocking it on a stream starves the background task that
    does the research. Browsers get the live stream; tests just need the result.
    """
    r = client.post("/api/onboarding/sessions", json=payload, headers=headers or {})
    assert r.status_code == 201, r.text
    session_id = r.json()["session_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = client.get(f"/api/onboarding/sessions/{session_id}").json()
        if snapshot["status"] != "running":
            break
        time.sleep(0.25)
    else:
        raise AssertionError(f"the agent was still running after {timeout}s")

    events = client.get(f"/api/onboarding/sessions/{session_id}/events?replay=1").json()
    return session_id, snapshot, events


def field(snapshot, key):
    return next(f for f in snapshot["ledger"]["fields"] if f["key"] == key)


def ran(events, tool):
    return any(e.get("type") == "step_done" and e.get("tool") == tool for e in events)


class TestResearch:
    def test_reads_the_website_and_verifies_what_it_can(self, client):
        _, snap, events = run_agent(client, {
            "website": "posthog.com", "email": "someone@posthog.com",
            "founder_name": "Test Person", "stage": "series_a"})
        assert ran(events, "website") and ran(events, "rdap") and ran(events, "dns")
        assert field(snap, "legal_name")["value"], "a company name was found"
        # The domain's age is gathered even when it cannot fill the field on its
        # own; with an empty corpus the founding year is asked of the founder.
        year = field(snap, "founded_year")
        assert any(e["source"] == "rdap" for e in year["evidence"]), "domain age was checked"
        assert year["status"] in ("verified", "fetched", "conflict", "missing")
        assert field(snap, "email")["status"] == "verified", "work email on the company domain"

    def test_skips_indian_registries_for_a_foreign_company(self, client):
        _, _, events = run_agent(client, {
            "website": "posthog.com", "email": "someone@posthog.com",
            "founder_name": "Test Person", "stage": "seed"})
        assert not ran(events, "mca21")
        assert any("Indian entity" in e.get("text", "") for e in events if e.get("type") == "thought")

    def test_personal_email_is_not_proof(self, client):
        _, snap, _ = run_agent(client, {
            "website": "posthog.com", "email": "someone@gmail.com",
            "founder_name": "Test Person", "stage": "seed"})
        row = field(snap, "email")
        assert row["status"] == "claimed" and "personal mailbox" in row["note"]

    def test_unreachable_website_is_flagged_not_ignored(self, client):
        _, snap, events = run_agent(client, {
            "website": "this-domain-should-not-resolve-viq.example",
            "email": "a@this-domain-should-not-resolve-viq.example",
            "founder_name": "Test Person", "stage": "idea", "legal_name": "Ghost Labs"})
        assert field(snap, "website")["status"] == "conflict"
        assert any("falling back" in e.get("text", "") for e in events if e.get("type") == "thought")


class TestGuards:
    def test_loopback_urls_are_refused(self, client):
        r = client.post("/api/onboarding/sessions", json={
            "website": "http://127.0.0.1:8000", "email": "a@b.co",
            "founder_name": "AB", "stage": "idea"})
        assert r.status_code == 422

    def test_needs_a_website_or_a_name(self, client):
        r = client.post("/api/onboarding/sessions", json={
            "email": "a@b.co", "founder_name": "AB", "stage": "idea"})
        assert r.status_code == 422

    def test_unknown_session_is_404(self, client):
        assert client.get("/api/onboarding/sessions/nope").status_code == 404


class TestSubmission:
    def test_a_company_nobody_knows_can_still_register(self, client, db):
        """The founder fills what no source has, and gets a real profile."""
        from app.models import Startup

        session_id, snap, _ = run_agent(client, {
            "email": "founder@example.com", "founder_name": "Rohit Verma",
            "stage": "idea", "legal_name": "Kisaan Mitra Labs"})
        missing = [f["key"] for f in snap["ledger"]["fields"] if f["status"] == "missing"]
        assert "sector" in missing

        fill = {"sector": "AgriTech", "founded_year": 2026, "hq_city": "Lucknow"}
        client.patch(f"/api/onboarding/sessions/{session_id}/fields",
                     json=[{"key": k, "value": v} for k, v in fill.items() if k in missing])
        snap = client.get(f"/api/onboarding/sessions/{session_id}").json()
        for f in snap["ledger"]["fields"]:
            if f["status"] == "conflict":
                client.patch(f"/api/onboarding/sessions/{session_id}/fields",
                             json=[{"key": f["key"], "resolution": "accept" if f["suggestion"] else "keep"}])

        r = client.post(f"/api/onboarding/sessions/{session_id}/submit")
        assert r.status_code == 200, r.text
        created = db.get(Startup, r.json()["startup_id"])
        assert created.legal_name == "Kisaan Mitra Labs" and created.latest_score is not None
        db.delete(created)
        db.commit()

    def test_submit_is_refused_while_something_is_unresolved(self, client):
        session_id, snap, _ = run_agent(client, {
            "email": "founder@example.com", "founder_name": "Rohit Verma",
            "stage": "seed", "legal_name": "Kisaan Mitra Labs"})
        r = client.post(f"/api/onboarding/sessions/{session_id}/submit")
        assert r.status_code == 422 and "Resolve these first" in r.text
