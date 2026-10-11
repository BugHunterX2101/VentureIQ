"""Sign in with Google (OAuth 2.0 authorization code flow).

    GET /api/auth/google/start?role=investor&next=/dashboard
    GET /api/auth/google/callback?code=…&state=…

Shape of the flow, and why:

- `state` is a short-lived signed token carrying the role, the page the visitor
  came from, and a nonce. Google hands it back untouched, which is what proves
  the callback belongs to a request we started (CSRF).
- The code is exchanged server-side, so the client secret never reaches the
  browser, and the profile is read from Google's userinfo endpoint.
- An existing account with the same email is linked rather than duplicated;
  the password (if any) keeps working.
- Our own session token goes back to the frontend in the URL *fragment*, which
  browsers do not send to servers or put in Referer headers.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, decode_token
from app.models import AuditLog, Investor, User

router = APIRouter(prefix="/api/auth/google", tags=["auth"])
log = logging.getLogger("viq.oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
STATE_TTL_SECONDS = 600


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _require_configured() -> None:
    if not configured():
        raise HTTPException(
            503,
            "Google sign-in isn't configured on this server "
            "(set VIQ_GOOGLE_CLIENT_ID and VIQ_GOOGLE_CLIENT_SECRET)",
        )


def _frontend(path: str, fragment: str = "") -> str:
    base = settings.frontend_url.rstrip("/")
    return f"{base}{path}{('#' + fragment) if fragment else ''}"


@router.get("/start")
def start(
    role: str = Query("investor", pattern="^(investor|founder)$"),
    next: str = Query("/dashboard", max_length=200),
):
    """Send the visitor to Google with a signed state."""
    _require_configured()
    state = create_access_token(
        f"oauth-{secrets.token_urlsafe(16)}",
        "oauth_state",
        {"role": role, "next": next if next.startswith("/") else "/dashboard", "purpose": "google"},
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=307)


async def _exchange(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        token_res = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            body = token_res.json() if token_res.headers.get("content-type", "").startswith("application/json") else {}
            raise HTTPException(401, body.get("error_description") or body.get("error")
                                or f"Google rejected the sign-in ({token_res.status_code})")
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise HTTPException(401, "Google did not return an access token")
        info_res = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if info_res.status_code != 200:
            raise HTTPException(401, "Could not read your Google profile")
        return info_res.json()


@router.get("/callback")
async def callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: Session = Depends(get_db),
):
    _require_configured()
    if error:
        log.warning("Google returned an error: %s (%s)", error, error_description)
        detail = urlencode({"error": error, "detail": error_description or ""})
        return RedirectResponse(_frontend("/login", detail), status_code=303)

    claims = decode_token(state)
    if not claims or claims.get("purpose") != "google" or claims.get("role") not in ("investor", "founder"):
        # Expired or forged: start again rather than trusting it.
        log.warning("Google callback with an unusable state token")
        return RedirectResponse(_frontend("/login", "error=expired_state"), status_code=303)
    if not code:
        return RedirectResponse(_frontend("/login", "error=no_code"), status_code=303)

    try:
        profile = await _exchange(code)
    except HTTPException as exc:
        log.warning("Google token exchange failed: %s", exc.detail)
        return RedirectResponse(
            _frontend("/login", urlencode({"error": "exchange_failed", "detail": str(exc.detail)})),
            status_code=303,
        )
    email = (profile.get("email") or "").strip().lower()
    if not email or not profile.get("email_verified", True):
        log.warning("Google profile has no verified email: %s", {k: profile.get(k) for k in ("sub", "email")})
        return RedirectResponse(_frontend("/login", "error=unverified_email"), status_code=303)

    user = (
        db.query(User).filter(User.provider_subject == profile.get("sub")).first()
        or db.query(User).filter(User.email == email).first()
    )
    created = False
    if user is None:
        role = claims["role"]
        user = User(
            email=email,
            name=(profile.get("name") or email.split("@")[0])[:160],
            role=role,
            auth_provider="google",
            provider_subject=profile.get("sub"),
            password_hash=None,
            # Set explicitly: column defaults are applied on INSERT, and this is
            # checked before the row is written.
            is_active=True,
        )
        if role == "investor":
            investor = Investor(name=user.name, email=email, investor_type="angel")
            db.add(investor)
            db.flush()
            user.investor_id = investor.investor_id
        db.add(user)
        created = True
    elif not user.provider_subject:
        # Existing password account, same person: link it.
        user.provider_subject = profile.get("sub")
    if user.is_active is False:
        log.warning("Google sign-in for a disabled account: %s", email)
        return RedirectResponse(_frontend("/login", "error=account_disabled"), status_code=303)

    user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    db.flush()
    db.add(AuditLog(actor_id=user.user_id, action="user.signed_in_with_google", entity_type="user",
                    entity_id=user.user_id, detail={"created": created}))
    db.commit()
    db.refresh(user)

    token = create_access_token(user.user_id, user.role,
                                {"investor_id": user.investor_id, "email": user.email})
    landing = "/my-companies" if user.role == "founder" else claims["next"]
    return RedirectResponse(
        _frontend("/auth/callback", urlencode({"token": token, "next": landing})),
        status_code=303,
    )
