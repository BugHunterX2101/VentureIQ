"""Agentic startup onboarding (report section 8.1: registration + enrichment).

    POST   /api/onboarding/sessions                 start; the agent runs in the background
    GET    /api/onboarding/sessions/{id}/events     live trace (Server-Sent Events)
    GET    /api/onboarding/sessions/{id}            ledger snapshot
    PATCH  /api/onboarding/sessions/{id}/fields     founder edits / conflict resolutions
    PUT    /api/onboarding/sessions/{id}/founders   founder list
    POST   /api/onboarding/sessions/{id}/founders/{i}/check   live GitHub check
    POST   /api/onboarding/sessions/{id}/submit     create the Startup
    GET    /api/onboarding/tools                    what each source does and how
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.api.deps import optional_user
from app.models import User
from app.onboarding import agent, checks
from app.onboarding.ledger import FIELDS, SPEC
from app.onboarding.tools import TOOLS
from app.schemas.dto import Stage

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# Keep background runs referenced so they aren't garbage-collected mid-flight.
_TASKS: set[asyncio.Task] = set()


class StartIn(BaseModel):
    website: str | None = Field(None, max_length=512)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    founder_name: str = Field(min_length=2, max_length=160)
    stage: Stage
    legal_name: str | None = Field(None, max_length=255)
    cin: str | None = Field(None, max_length=32)
    gstin: str | None = Field(None, max_length=20)
    gst_consent: bool = False

    @field_validator("website", "legal_name", "cin", "gstin", mode="before")
    @classmethod
    def blank_to_none(cls, v: Any) -> Any:
        return v.strip() or None if isinstance(v, str) else v

    @field_validator("website")
    @classmethod
    def website_shape(cls, v: str | None) -> str | None:
        if v is None:
            return v
        url = checks.normalise_website(v)
        host = (urlsplit(url).hostname or "").lower()
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            is_ip = False
        if is_ip or host == "localhost" or not re.search(r"\.[a-z]{2,}$", host):
            raise ValueError("Use your company's domain name, e.g. acme.com")
        return url


class FieldEdit(BaseModel):
    key: str
    value: Any = None
    resolution: str | None = Field(None, pattern="^(accept|keep)$")


class FounderIn(BaseModel):
    name: str = Field(max_length=160)
    role: str | None = Field(None, max_length=96)
    github: str | None = Field(None, max_length=96)
    linkedin: str | None = Field(None, max_length=512)


def _run_or_404(session_id: str) -> agent.Run:
    run = agent.get_run(session_id)
    if run is None:
        raise HTTPException(404, "Onboarding session not found")
    return run


@router.get("/tools")
def tools():
    return {
        "tools": [{"id": k, **v} for k, v in TOOLS.items()],
        "fields": [
            {"key": f.key, "label": f.label, "group": f.group, "required": f.required,
             "founder_only": f.founder_only, "readonly": f.readonly, "hint": f.hint}
            for f in FIELDS
        ],
    }


@router.post("/sessions", status_code=201)
async def start(payload: StartIn, user: User | None = Depends(optional_user)):
    if not payload.website and not payload.legal_name:
        raise HTTPException(422, "Give us a website, or the company name if you don't have one yet")
    # Anonymous registration still works; signing in ties the company to you.
    run = agent.create_session(payload.model_dump(), user_id=user.user_id if user else None)
    task = asyncio.create_task(agent.execute(run))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"session_id": run.session_id}


@router.get("/sessions/{session_id}")
def snapshot(session_id: str):
    return _run_or_404(session_id).snapshot()


@router.get("/sessions/{session_id}/events")
async def events(session_id: str, request: Request, replay: bool = False):
    run = _run_or_404(session_id)
    if replay:
        # Plain JSON of what has been emitted so far; the stream below is what
        # browsers use. Handy for tests and for debugging a finished session.
        return run.events

    async def stream():
        sent = 0
        version = -1
        yield "retry: 2000\n\n"
        while True:
            while sent < len(run.events):
                ev = run.events[sent]
                sent += 1
                yield f"id: {ev['seq']}\ndata: {json.dumps(ev, default=str)}\n\n"
            if run.status == "running" and version != run.state_version:
                version = run.state_version
                yield f"event: state\ndata: {json.dumps(run.snapshot(), default=str)}\n\n"
            if run.status != "running":
                yield f"event: snapshot\ndata: {json.dumps(run.snapshot(), default=str)}\n\n"
                return
            if await request.is_disconnected():
                return
            try:
                await asyncio.wait_for(run.wait(), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/sessions/{session_id}/fields")
async def edit_fields(session_id: str, edits: list[FieldEdit]):
    run = _run_or_404(session_id)
    if run.status == "submitted":
        raise HTTPException(409, "Already submitted")
    for e in edits:
        spec = SPEC.get(e.key)
        if spec is None or spec.readonly:
            raise HTTPException(422, f"{e.key} can't be edited")
        if e.key == "stage":
            if e.value not in ("idea", "seed", "series_a", "series_b_plus", "growth"):
                raise HTTPException(422, "Unknown stage")
            run.inputs["stage"] = e.value
            continue
        await agent.apply_edit(run, e.key, e.value, e.resolution)
    run.save()
    return run.snapshot()


@router.put("/sessions/{session_id}/founders")
async def put_founders(session_id: str, founders: list[FounderIn]):
    run = _run_or_404(session_id)
    agent.set_founders(run, [f.model_dump() for f in founders])
    return run.snapshot()


@router.post("/sessions/{session_id}/founders/{index}/check")
async def check_founder(session_id: str, index: int):
    run = _run_or_404(session_id)
    if not 0 <= index < len(run.facts.get("founders", [])):
        raise HTTPException(404, "No such founder")
    await agent.check_founder(run, index)
    return run.snapshot()


@router.post("/sessions/{session_id}/submit")
async def submit(session_id: str):
    run = _run_or_404(session_id)
    if run.status == "submitted":
        return {"startup_id": run.startup_id}
    if run.status == "running":
        raise HTTPException(409, "The agent is still researching")
    try:
        startup_id = await agent.submit(run)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"startup_id": startup_id}
