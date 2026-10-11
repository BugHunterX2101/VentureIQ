"""India's company registry (MCA master data) — search any registered company,
and see whether it already has a VentureIQ profile.

    GET /api/registry/status
    GET /api/registry/search?q=&state=&active_only=&since=&limit=
    GET /api/registry/{cin}
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Startup
from app.onboarding.checks import decode_cin
from app.registry import store

router = APIRouter(prefix="/api/registry", tags=["registry"])


def _with_platform(db: Session, rows: list[dict]) -> list[dict]:
    """Attach the VentureIQ profile id when a registry company is already listed."""
    if not rows:
        return rows
    cins = [r["cin"] for r in rows]
    by_cin = dict(db.query(Startup.cin, Startup.startup_id).filter(Startup.cin.in_(cins)).all())
    names = [r["name"].lower() for r in rows]
    by_name = dict(
        db.query(func.lower(Startup.legal_name), Startup.startup_id)
        .filter(func.lower(Startup.legal_name).in_(names))
        .all()
    )
    for r in rows:
        r["startup_id"] = by_cin.get(r["cin"]) or by_name.get(r["name"].lower())
    return rows


@router.get("/status")
def status():
    return store.stats()


@router.get("/search")
async def search(
    q: str = Query(..., min_length=2, max_length=120),
    state: str | None = None,
    active_only: bool = False,
    since: str | None = Query(None, pattern=r"^\d{4}(-\d{2}-\d{2})?$"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    rows = await asyncio.to_thread(store.search_local, q, limit, state, active_only, since)
    how = "local"
    # Without a full import, an exact CIN can still be answered live.
    if not rows and decode_cin(q)["valid"]:
        try:
            rec, how = await store.lookup_cin(q)
        except httpx.HTTPError:
            rec = None
        rows = [rec] if rec else []
    stats = store.stats()
    return {
        "items": _with_platform(db, rows),
        "source": how,
        "registry": {"companies": stats["companies"], "complete": stats.get("complete", False)},
    }


@router.get("/{cin}")
async def company(cin: str, db: Session = Depends(get_db)):
    try:
        rec, how = await store.lookup_cin(cin)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(503, f"Registry unavailable (HTTP {exc.response.status_code})") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Registry unavailable") from exc
    if not rec:
        raise HTTPException(404, "No company with this CIN in the MCA registry")
    return {**_with_platform(db, [rec])[0], "source": how}
