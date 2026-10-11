"""Document intelligence (report Layer 2).

    POST /api/startups/{id}/documents            upload, read, verify, keep
    GET  /api/startups/{id}/documents            what has been uploaded
    POST /api/onboarding/sessions/{id}/documents  same, feeding the ledger
    GET  /api/documents/capabilities             what this deployment can read

OCR is Tesseract; the fields are the ones VentureIQ can actually check (CIN,
GSTIN, registered name, incorporation date, revenue), and each upload is
cross-checked against the MCA registry and the claims already on file.
Files are stored on disk beside the database; S3 is the production target and
is what `s3_key` is named for.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload

from app.api.deps import current_user
from app.core.config import ARTIFACTS
from app.core.database import get_db
from app.documents import extract, ocr
from app.models import AuditLog, Startup, StartupDocument, User

router = APIRouter(tags=["documents"])

UPLOAD_ROOT = Path(ARTIFACTS) / "uploads"
MAX_BYTES = 12 * 1024 * 1024
ALLOWED = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
           ".jpeg": "image/jpeg", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "document").name)
    return cleaned[-120:] or "document"


async def _store(upload: UploadFile, folder: str) -> tuple[Path, str, int]:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, f"Upload a PDF or an image ({', '.join(sorted(ALLOWED))})")
    body = await upload.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise HTTPException(413, f"Keep files under {MAX_BYTES // (1024 * 1024)} MB")
    if not body:
        raise HTTPException(400, "That file is empty")
    target_dir = UPLOAD_ROOT / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(body)
    return path, _safe_name(upload.filename or ""), len(body)


def _read_and_extract(path: Path, startup: Startup | None) -> dict[str, Any]:
    try:
        result = ocr.read(path)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(503, f"Couldn't read that document: {exc}") from exc

    doc_type, type_confidence = extract.detect_type(result.text)
    fields = extract.extract(result.text, doc_type)
    checks = extract.verify(fields, startup)
    return {
        "doc_type": doc_type,
        "doc_type_label": extract.DOC_TYPES[doc_type],
        "type_confidence": type_confidence,
        "engine": result.engine,
        "pages": result.pages,
        "ocr_confidence": round(result.confidence, 3) if result.confidence is not None else None,
        "warnings": result.warnings,
        "fields": [f.as_dict() for f in fields],
        "checks": checks,
        "text_preview": re.sub(r"\n{3,}", "\n\n", result.text.strip())[:1200],
        "text": result.text,
    }


@router.get("/api/documents/capabilities")
def capabilities():
    ok, why = ocr.available()
    return {
        "ocr_available": ok,
        "detail": why,
        "max_file_mb": MAX_BYTES // (1024 * 1024),
        "accepted": sorted(ALLOWED),
        "document_types": [{"id": k, "label": v} for k, v in extract.DOC_TYPES.items()],
        "checks": [
            "CIN is looked up in the MCA Company Master Data",
            "The registered name and incorporation date are compared with the registry",
            "GSTIN check digit, and its embedded PAN against any PAN on the document",
            "Revenue is compared with what the profile reports",
        ],
    }


@router.get("/api/startups/{startup_id}/documents")
def list_documents(startup_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(StartupDocument)
        .filter(StartupDocument.startup_id == startup_id)
        .order_by(StartupDocument.uploaded_at.desc())
        .all()
    )
    return [
        {
            "document_id": d.document_id,
            "doc_type": d.doc_type,
            "doc_type_label": extract.DOC_TYPES.get(d.doc_type, d.doc_type),
            "filename": d.filename,
            "uploaded_at": d.uploaded_at,
            "extraction_confidence": d.extraction_confidence,
            "fields": (d.layoutlm_entities or {}).get("fields", []),
            "checks": d.deviation_flags or [],
        }
        for d in rows
    ]


@router.post("/api/startups/{startup_id}/documents", status_code=201)
async def upload_document(
    startup_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    startup = (
        db.query(Startup)
        .options(selectinload(Startup.financials))
        .filter(Startup.startup_id == startup_id)
        .first()
    )
    if not startup:
        raise HTTPException(404, "Startup not found")
    # Documents are evidence about a company, so only its founder may add them.
    if startup.owner_user_id and startup.owner_user_id != user.user_id:
        raise HTTPException(403, "Only the founder who registered this company can upload its documents")

    path, filename, size = await _store(file, startup_id)
    parsed = _read_and_extract(path, startup)

    doc = StartupDocument(
        startup_id=startup_id,
        doc_type=parsed["doc_type"],
        filename=filename,
        s3_key=str(path.relative_to(ARTIFACTS)),
        ocr_text=parsed["text"][:200_000],
        layoutlm_entities={"fields": parsed["fields"], "engine": parsed["engine"],
                           "pages": parsed["pages"], "type_confidence": parsed["type_confidence"]},
        extraction_confidence=parsed["ocr_confidence"],
        deviation_flags=parsed["checks"],
    )
    db.add(doc)
    db.add(AuditLog(actor_id=user.user_id, action="document.uploaded", entity_type="startup",
                    entity_id=startup_id,
                    detail={"doc_type": parsed["doc_type"], "bytes": size,
                            "conflicts": [c["check"] for c in parsed["checks"] if c["status"] == "conflict"]}))
    db.commit()
    db.refresh(doc)

    parsed.pop("text")
    return {"document_id": doc.document_id, "filename": filename, **parsed}


@router.post("/api/onboarding/sessions/{session_id}/documents", status_code=201)
async def upload_during_onboarding(session_id: str, file: UploadFile = File(...)):
    """Upload a certificate while registering: what it proves lands in the ledger."""
    from app.onboarding import agent

    run = agent.get_run(session_id)
    if run is None:
        raise HTTPException(404, "Onboarding session not found")
    if run.status == "submitted":
        raise HTTPException(409, "This registration is already submitted")

    path, filename, _ = await _store(file, f"session-{session_id}")
    parsed = _read_and_extract(path, None)
    agent.apply_document(run, filename, path, parsed)
    parsed.pop("text")
    return {"filename": filename, **parsed, "snapshot": run.snapshot()}
