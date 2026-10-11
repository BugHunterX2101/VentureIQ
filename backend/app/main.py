"""VentureIQ API.

Layer 1 (Infrastructure) in the report's terms: every request enters through
here, and auth/KYC middleware would sit at this boundary in production.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import (
    analytics, auth, documents, investors, kyc, marketplace, oauth, onboarding, registry, startups,
    mentorship,
)
from app.core.config import settings
from app.core.database import Base, engine, ensure_columns


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Agentic AI and RAG-powered startup investment intelligence. "
        "Marketplace endpoints are SIMULATED — see docs/BUILD_PLAN.md Problem 1."
    ),
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing(request: Request, call_next):
    """Latency header — the observability hook the report's Layer 1 calls for."""
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
    return response


app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(startups.router)
app.include_router(investors.router)
app.include_router(investors.events_router)
app.include_router(analytics.router)
app.include_router(analytics.market)
app.include_router(onboarding.router)
app.include_router(registry.router)
app.include_router(documents.router)
app.include_router(kyc.router)
app.include_router(marketplace.router)
app.include_router(mentorship.router)


@app.get("/api/health", tags=["health"])
def health():
    from app.core.database import SessionLocal
    from app.ml.train import FRAUD_MODEL_PATH, MODEL_PATH

    db = SessionLocal()
    try:
        from sqlalchemy import func

        from app.models import Startup

        n = db.query(func.count(Startup.startup_id)).scalar() or 0
    except Exception:
        n = -1
    finally:
        db.close()

    return {
        "status": "ok",
        "version": settings.version,
        "startups_indexed": n,
        "growth_model_trained": MODEL_PATH.exists(),
        "fraud_model_trained": FRAUD_MODEL_PATH.exists(),
    }
