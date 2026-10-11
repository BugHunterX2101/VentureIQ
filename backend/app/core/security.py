"""Password hashing and JWT issuing (report Layer 1: Auth & KYC).

Passwords are bcrypt-hashed; tokens are signed JWTs carrying the user id, role
and, for investors, the investor they own. Nothing here trusts the client: the
role on the token is re-read from the database on every protected request, so a
stolen or stale token cannot grant a role the account no longer has.
"""

from __future__ import annotations

import secrets
from threading import Lock
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import ARTIFACTS, settings

ALGORITHM = "HS256"
# bcrypt hashes at most 72 bytes and silently ignores the rest, so the API
# rejects longer passwords rather than pretending they were used in full.
MAX_PASSWORD_BYTES = 72
_SECRET_FILE = Path(ARTIFACTS) / "jwt_secret.txt"


def _secret() -> str:
    """The signing key: from config, else a persisted local one.

    Generating it on demand keeps local development one command, while a
    deployment sets VIQ_JWT_SECRET so tokens survive restarts and are not
    readable from the repo.
    """
    if settings.jwt_secret:
        return settings.jwt_secret
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    generated = secrets.token_urlsafe(48)
    _SECRET_FILE.write_text(generated)
    _SECRET_FILE.chmod(0o600)
    return generated


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:MAX_PASSWORD_BYTES], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:MAX_PASSWORD_BYTES], hashed.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, role: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        **(extra or {}),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None


# --------------------------------------------------------------------------
# login throttling
# --------------------------------------------------------------------------

# Failed sign-in attempts, keyed by email and by client address. In-process and
# therefore per-worker: it raises the cost of guessing a password from
# unlimited to a few per minute, which is what it is for. A deployment behind
# several workers wants this in Redis, and a public one wants it at the edge
# as well.
_ATTEMPT_WINDOW = timedelta(minutes=15)
_MAX_ATTEMPTS = 8
_attempts: dict[str, list[datetime]] = {}
_attempts_lock = Lock()


def _recent(key: str, now: datetime) -> list[datetime]:
    return [t for t in _attempts.get(key, []) if now - t < _ATTEMPT_WINDOW]


def login_blocked(*keys: str) -> int:
    """Seconds to wait before the next attempt, or 0 when not throttled."""
    now = datetime.now(UTC)
    with _attempts_lock:
        for key in keys:
            recent = _recent(key, now)
            _attempts[key] = recent
            if len(recent) >= _MAX_ATTEMPTS:
                return max(1, int((recent[0] + _ATTEMPT_WINDOW - now).total_seconds()))
    return 0


def record_failed_login(*keys: str) -> None:
    now = datetime.now(UTC)
    with _attempts_lock:
        for key in keys:
            _attempts[key] = [*_recent(key, now), now]


def clear_failed_logins(*keys: str) -> None:
    with _attempts_lock:
        for key in keys:
            _attempts.pop(key, None)
