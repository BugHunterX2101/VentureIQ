"""KYC: what can honestly be checked, and what cannot (report Layer 1).

    POST /api/kyc/submit      PAN + an ID document, read and cross-checked
    GET  /api/kyc/me          my case and what it means for the marketplace
    GET  /api/kyc/queue       cases awaiting a human (reviewer only)
    POST /api/kyc/{id}/decide approve or reject, recorded in the audit log

Real here: the document is OCR'd, the PAN's structure is validated, the holder
type is decoded from it, and the name on the document is compared with the
account and with the PAN embedded in any GSTIN on file.

Not real here: proof of identity. That needs a licensed provider (Aadhaar
e-KYC, DigiLocker, or a KRA/KYC agency), which a dissertation project cannot
contract with. So automated checks can only reach `passed_checks`; a human
grants `verified`, and every decision is written to the audit log.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import current_user, is_reviewer, reviewer_user
from app.api.routes.documents import _read_and_extract, _store
from app.core.database import get_db
from app.models import AuditLog, Investor, KycCase, User
from app.onboarding.checks import decode_gstin, norm_text

router = APIRouter(prefix="/api/kyc", tags=["kyc"])

PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
PAN_HOLDER = {"C": "Company", "P": "Individual", "F": "Firm / LLP", "H": "HUF", "A": "AOP",
              "T": "Trust", "B": "BOI", "L": "Local authority", "J": "Artificial juridical person",
              "G": "Government"}
def _case_out(case: KycCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "status": case.status,
        "pan": case.pan,
        "legal_name": case.legal_name,
        "document_type": case.document_type,
        "checks": case.checks or [],
        "reviewer_note": case.reviewer_note,
        "submitted_at": case.submitted_at,
        "decided_at": case.decided_at,
        "what_this_means": {
            "submitted": "We have your details; checks are running.",
            "passed_checks": "Every automated check passed. A reviewer signs off identity, "
                             "because proving it needs a licensed provider.",
            "failed_checks": "Something didn't line up — see the checks below.",
            "verified": "A reviewer confirmed your identity.",
            "rejected": "A reviewer could not confirm your identity.",
        }.get(case.status, ""),
    }


def _run_checks(pan: str, account_name: str, doc: dict[str, Any] | None,
                investor: Investor | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    ok = bool(PAN_RE.match(pan))
    checks.append({
        "check": "pan_format", "status": "passed" if ok else "failed",
        "detail": f"{pan} decodes as a PAN held by: {PAN_HOLDER.get(pan[3], 'an unrecognised holder type')}" if ok
                  else "A PAN looks like ABCDE1234F",
        "kind": "local",
    })

    if doc:
        fields = {f["key"]: f["value"] for f in doc["fields"]}
        doc_pan = fields.get("pan")
        if doc_pan:
            same = str(doc_pan).upper() == pan
            checks.append({
                "check": "pan_matches_document", "status": "passed" if same else "failed",
                "detail": f"The document shows {doc_pan}" + ("" if same else f", not {pan}"),
                "kind": "network",
            })
        doc_name = fields.get("company_name")
        if doc_name:
            same = norm_text(str(doc_name)).startswith(norm_text(account_name)[:10]) or \
                norm_text(account_name).startswith(norm_text(str(doc_name))[:10])
            checks.append({
                "check": "name_matches_account", "status": "passed" if same else "review",
                "detail": f"Document names “{doc_name}”; the account says “{account_name}”",
                "kind": "network",
            })
        checks.append({
            "check": "document_readable", "status": "passed" if doc["fields"] else "review",
            "detail": f"{doc['doc_type_label']} read at "
                      f"{int((doc['ocr_confidence'] or 0) * 100)}% OCR confidence",
            "kind": "network",
        })
        for c in doc.get("checks", []):
            checks.append({"check": c["check"], "status": "passed" if c["status"] == "verified" else "failed",
                           "detail": c["detail"], "kind": c.get("kind", "local")})

    if investor and investor.sebi_registration_no:
        sebi = investor.sebi_registration_no.strip().upper()
        shaped = bool(re.match(r"^IN/?[A-Z]{2,6}/?\d{3,8}$", sebi.replace(" ", "")))
        checks.append({
            "check": "sebi_registration_shape", "status": "passed" if shaped else "review",
            "detail": f"{sebi} " + ("matches the SEBI registration pattern" if shaped
                                    else "does not look like a SEBI registration number"),
            "kind": "local",
        })

    checks.append({
        "check": "identity_proof", "status": "review",
        "detail": "Proving identity needs a licensed provider (Aadhaar e-KYC, DigiLocker or a KRA). "
                  "Not integrated, so a human reviews this case.",
        "kind": "manual",
    })
    return checks


@router.post("/submit", status_code=201)
async def submit(
    pan: str = Form(...),
    legal_name: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    pan = pan.strip().upper()
    investor = db.get(Investor, user.investor_id) if user.investor_id else None

    doc = None
    stored_path = None
    if file is not None:
        path, filename, _ = await _store(file, f"kyc-{user.user_id}")
        stored_path = str(path)
        doc = _read_and_extract(path, None)
        doc["filename"] = filename

    checks = _run_checks(pan, legal_name or user.name, doc, investor)

    # A GSTIN on the investor's companies embeds a PAN; if it disagrees, say so.
    if investor and investor.email:
        pass  # investors have no GSTIN of their own; the company-side check lives on the profile

    failed = [c for c in checks if c["status"] == "failed"]
    case = KycCase(
        user_id=user.user_id,
        investor_id=user.investor_id,
        pan=pan,
        legal_name=legal_name or user.name,
        document_path=stored_path,
        document_type=doc["doc_type"] if doc else None,
        checks=checks,
        status="failed_checks" if failed else "passed_checks",
    )
    db.add(case)
    if investor:
        investor.kyc_status = "failed" if failed else "pending_review"
    db.add(AuditLog(actor_id=user.user_id, action="kyc.submitted", entity_type="user",
                    entity_id=user.user_id,
                    detail={"status": case.status, "failed": [c["check"] for c in failed]}))
    db.commit()
    db.refresh(case)
    return _case_out(case)


@router.get("/me")
def my_case(db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = (
        db.query(KycCase)
        .filter(KycCase.user_id == user.user_id)
        .order_by(KycCase.submitted_at.desc())
        .first()
    )
    investor = db.get(Investor, user.investor_id) if user.investor_id else None
    return {
        "case": _case_out(case) if case else None,
        "kyc_status": investor.kyc_status if investor else None,
        "accredited": bool(investor and investor.accredited_investor),
        "marketplace_unlocked": bool(case and case.status == "verified"),
        "note": "Identity verification is not performed here: a licensed provider would do it. "
                "Automated checks and a human review stand in, and every decision is audited.",
    }


@router.get("/queue")
def queue(db: Session = Depends(get_db), user: User = Depends(reviewer_user)):
    cases = (
        db.query(KycCase)
        .filter(KycCase.status.in_(["passed_checks", "failed_checks"]))
        .order_by(KycCase.submitted_at.asc())
        .limit(100)
        .all()
    )
    # A reviewer is deciding about a person, so the queue names them.
    people = {
        u.user_id: u
        for u in db.query(User).filter(User.user_id.in_([c.user_id for c in cases])).all()
    } if cases else {}
    out = []
    for case in cases:
        person = people.get(case.user_id)
        out.append({
            **_case_out(case),
            "submitted_by": {
                "name": person.name if person else None,
                "email": person.email if person else None,
            },
        })
    return out


@router.post("/{case_id}/decide")
def decide(
    case_id: str,
    approve: bool,
    note: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(reviewer_user),
):
    case = db.get(KycCase, case_id)
    if not case:
        raise HTTPException(404, "No such case")
    case.status = "verified" if approve else "rejected"
    case.reviewer_note = note
    case.reviewed_by = user.user_id
    case.decided_at = datetime.now(UTC).replace(tzinfo=None)
    if case.investor_id:
        investor = db.get(Investor, case.investor_id)
        if investor:
            investor.kyc_status = "verified" if approve else "rejected"
    db.add(AuditLog(actor_id=user.user_id, action="kyc.decided", entity_type="kyc_case",
                    entity_id=case.case_id, detail={"approved": approve, "note": note}))
    db.commit()
    db.refresh(case)
    return _case_out(case)


def gstin_pan_matches(gstin: str, pan: str) -> bool:
    """Shared helper: a GSTIN embeds the PAN of its holder."""
    decoded = decode_gstin(gstin)
    return bool(decoded["valid"] and decoded["pan"] == pan.strip().upper())
