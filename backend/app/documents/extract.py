"""Pull startup facts out of OCR'd documents, then check them.

The bill parser in `ocr-service/` proves the shape of this: regex plus
heuristics over OCR text, with a confidence per field. What differs is *which*
fields matter here, and that VentureIQ can then verify them — a CIN read off a
certificate is looked up in the MCA registry, a GSTIN is checksum-validated,
and a stated revenue is compared with what the founder claimed.

Anything a document asserts is still only a claim until a source agrees, so
every field carries where it came from and how sure we are.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app.onboarding.checks import decode_cin, decode_gstin, norm_text

DOC_TYPES = {
    "incorporation_certificate": "Certificate of Incorporation",
    "gst_certificate": "GST registration certificate",
    "financial_statement": "Financial statement",
    "bank_statement": "Bank statement",
    "pitch_deck": "Pitch deck",
    "other": "Unrecognised document",
}

_TYPE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("incorporation_certificate",
     ("certificate of incorporation", "ministry of corporate affairs", "registrar of companies",
      "corporate identity number", "date of incorporation")),
    ("gst_certificate",
     ("goods and services tax", "registration certificate", "gstin", "gst identification number",
      "central goods and services")),
    ("financial_statement",
     ("balance sheet", "profit and loss", "statement of profit", "total revenue", "auditor",
      "revenue from operations", "income statement")),
    ("bank_statement",
     ("statement of account", "closing balance", "ifsc", "account number", "withdrawal", "deposit")),
    ("pitch_deck", ("problem", "solution", "traction", "market size", "ask", "go to market")),
]

# Scanned text confuses these constantly. A repair is only ever accepted when
# something independent agrees: the GSTIN check digit, or the MCA registry.
_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
                           "S": "5", "B": "8", "G": "6", "T": "7", "A": "4"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"})
# Identifier layouts: D = digit, A = letter, X = either.
CIN_SHAPE = "ADDDDDAADDDDAAADDDDDD"
GSTIN_SHAPE = "DDAAAAADDDDAXZX"
PAN_SHAPE = "AAAAADDDDA"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]{8,24}")


def _coerce(token: str, shape: str) -> str | None:
    """Force a token into an identifier's shape, fixing only ambiguous glyphs."""
    if len(token) != len(shape):
        return None
    out = []
    for ch, want in zip(token.upper(), shape, strict=True):
        if want == "D":
            ch = ch.translate(_TO_DIGIT)
            if not ch.isdigit():
                return None
        elif want == "A":
            ch = ch.translate(_TO_ALPHA)
            if not ch.isalpha():
                return None
        elif want == "Z":
            ch = "Z" if ch in "Z2" else ch
            if ch != "Z":
                return None
        elif want == "X" and not ch.isalnum():
            return None
        out.append(ch)
    return "".join(out)


def _repaired(text: str, shape: str, accept) -> tuple[str, str] | None:
    """(repaired value, original token) for the first candidate `accept` likes."""
    for m in _TOKEN_RE.finditer(text):
        token = m.group(0)
        fixed = _coerce(token, shape)
        if fixed and fixed != token.upper() and accept(fixed):
            return fixed, token
    return None


CIN_RE = re.compile(r"\b([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b")
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")
DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
MONTH_DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\,?\s+(\d{4})\b", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
# "2.5 crore", "Rs 25,00,000", "$1.2M". A bare small number is ignored unless a
# unit follows it, so stray page numbers are not read as revenue.
AMOUNT_RE = r"(?:rs\.?|inr|₹|\$)?\s*([\d][\d,]*(?:\.\d{1,2})?)\s*(crore|cr\b|lakh|lakhs|million|mn\b|bn\b|k\b)?"


@dataclass
class Field:
    key: str
    value: Any
    confidence: float
    evidence: str          # the line it was read from
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_type(text: str) -> tuple[str, float]:
    low = re.sub(r"\s+", " ", text.lower())
    best, best_hits = "other", 0
    for kind, hints in _TYPE_HINTS:
        hits = sum(1 for h in hints if h in low)
        if hits > best_hits:
            best, best_hits = kind, hits
    confidence = min(0.5 + 0.15 * best_hits, 0.97) if best_hits else 0.2
    return best, round(confidence, 2)


def _line_for(text: str, needle: str) -> str:
    for line in text.splitlines():
        if needle and needle in line:
            return re.sub(r"\s+", " ", line).strip()[:200]
    return ""


def _to_number(raw: str, unit: str | None) -> float:
    n = float(raw.replace(",", ""))
    scale = {"crore": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "million": 1e6,
             "mn": 1e6, "bn": 1e9, "k": 1e3}.get((unit or "").strip().lower(), 1)
    return n * scale


def _find_date(text: str, keywords: tuple[str, ...]) -> tuple[date | None, str]:
    for line in text.splitlines():
        low = line.lower()
        if not any(k in low for k in keywords):
            continue
        m = MONTH_DATE_RE.search(line)
        if m:
            day, month, year = int(m.group(1)), MONTHS.index(m.group(2).lower()) + 1, int(m.group(3))
            try:
                return date(year, month, day), re.sub(r"\s+", " ", line).strip()[:200]
            except ValueError:
                pass
        m = DATE_RE.search(line)
        if m:
            d, mth, y = (int(x) for x in m.groups())
            if d > 12 and mth <= 12:
                pass
            elif mth > 12:
                d, mth = mth, d
            try:
                return date(y, mth, d), re.sub(r"\s+", " ", line).strip()[:200]
            except ValueError:
                continue
    return None, ""


def _company_name(text: str) -> Field | None:
    """A registered name on a certificate, e.g. "…name of ACME ROBOTICS PRIVATE LIMITED…"."""
    patterns = [
        r"(?:name of (?:the )?company|company name)\s*[:\-]?\s*([A-Z][A-Za-z0-9&.,''\- ]{3,90}?(?:PRIVATE LIMITED|LIMITED|LLP))",
        r"\b([A-Z][A-Z0-9&.,''\- ]{3,90}?(?:PRIVATE LIMITED|LIMITED|LLP))\b",
    ]
    for i, pattern in enumerate(patterns):
        m = re.search(pattern, text, re.I if i == 0 else 0)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" .,-")
            return Field("company_name", name.title(), 0.85 if i == 0 else 0.6, _line_for(text, m.group(1)[:24]))
    return None


def extract(text: str, doc_type: str) -> list[Field]:
    """Fields worth having from this document, best-effort."""
    fields: list[Field] = []

    cin_found = False
    for m in CIN_RE.finditer(text):
        decoded = decode_cin(m.group(1))
        if decoded["valid"]:
            fields.append(Field("cin", decoded["cin"], 0.95, _line_for(text, m.group(1)),
                                f"{decoded['company_type']}, {decoded['state']}, {decoded['incorporation_year']}"))
            cin_found = True
            break
    if not cin_found:
        from app.registry import store as registry

        # A repaired CIN counts only if that company actually exists.
        repair = _repaired(text, CIN_SHAPE,
                           lambda v: decode_cin(v)["valid"] and registry.get_local(v) is not None)
        if repair:
            fixed, original = repair
            decoded = decode_cin(fixed)
            fields.append(Field("cin", fixed, 0.8, _line_for(text, original),
                                f"OCR read “{original}”; corrected to a CIN that exists in the MCA registry "
                                f"({decoded['state']}, {decoded['incorporation_year']})"))
    gstin_found = False
    for m in GSTIN_RE.finditer(text):
        decoded = decode_gstin(m.group(1))
        fields.append(Field("gstin", decoded["gstin"], 0.95 if decoded["valid"] else 0.5,
                            _line_for(text, m.group(1)),
                            "checksum valid" if decoded["valid"] else decoded.get("error", "")))
        gstin_found = True
        break
    if not gstin_found:
        # Accept a repair only if the check digit then validates.
        repair = _repaired(text, GSTIN_SHAPE, lambda v: decode_gstin(v)["valid"])
        if repair:
            fixed, original = repair
            fields.append(Field("gstin", fixed, 0.8, _line_for(text, original),
                                f"OCR read “{original}”; corrected to a GSTIN whose check digit validates"))
    if doc_type in ("gst_certificate", "financial_statement"):
        pan_hit = next((m.group(1) for m in PAN_RE.finditer(text)), None)
        if pan_hit:
            fields.append(Field("pan", pan_hit, 0.7, _line_for(text, pan_hit)))
        else:
            gstin_field = next((f for f in fields if f.key == "gstin"), None)
            embedded = decode_gstin(str(gstin_field.value))["pan"] if gstin_field else None
            repair = _repaired(text, PAN_SHAPE, lambda v: embedded is None or v == embedded)
            if repair:
                fixed, original = repair
                fields.append(Field("pan", fixed, 0.75, _line_for(text, original),
                                    f"OCR read “{original}”; corrected to {fixed}"))

    name = _company_name(text)
    if name:
        fields.append(name)

    if doc_type in ("incorporation_certificate", "gst_certificate"):
        when, line = _find_date(text, ("incorporat", "registration", "date of validity", "effective date"))
        if when:
            fields.append(Field("incorporation_date", when.isoformat(), 0.85, line))

    if doc_type in ("financial_statement", "bank_statement"):
        for key, keywords in (
            ("revenue", ("revenue from operations", "total revenue", "total income", "net sales", "turnover")),
            ("closing_balance", ("closing balance", "balance as on", "available balance")),
        ):
            for line in text.splitlines():
                low = line.lower()
                if not any(k in low for k in keywords):
                    continue
                for m in re.finditer(AMOUNT_RE, low):
                    digits = m.group(1).replace(",", "").split(".")[0]
                    if not m.group(2) and len(digits) < 4:
                        continue  # too small to be a reported figure without a unit
                    fields.append(Field(key, _to_number(m.group(1), m.group(2)), 0.65,
                                        re.sub(r"\s+", " ", line).strip()[:200],
                                        "read from the document; units can be misread"))
                    break
                else:
                    continue
                break

    return fields


def verify(fields: list[Field], startup: Any | None) -> list[dict[str, Any]]:
    """Check what the document says against the registry and the claims on file."""
    from app.registry import store as registry

    out: list[dict[str, Any]] = []
    by_key = {f.key: f for f in fields}

    cin = by_key.get("cin")
    if cin:
        record = registry.get_local(str(cin.value))
        if record:
            doc_name = by_key.get("company_name")
            name_ok = (
                None if not doc_name
                else norm_text(record["name"]).startswith(norm_text(str(doc_name.value))[:12])
                or norm_text(str(doc_name.value)).startswith(norm_text(record["name"])[:12])
            )
            out.append({
                "check": "cin_in_registry", "status": "verified",
                "detail": f"{record['name']} — {record['status']}, incorporated {record['registered']}",
                "source": "MCA Company Master Data", "kind": "dataset",
                "registry": {k: record.get(k) for k in ("cin", "name", "status", "registered", "state", "city")},
            })
            if name_ok is False:
                out.append({"check": "name_matches_registry", "status": "conflict",
                            "detail": f"The document names “{doc_name.value}”, the registry “{record['name']}”",
                            "source": "MCA Company Master Data", "kind": "dataset"})
            doc_date = by_key.get("incorporation_date")
            if doc_date and record.get("registered"):
                same = str(doc_date.value)[:10] == record["registered"][:10]
                out.append({
                    "check": "incorporation_date_matches_registry",
                    "status": "verified" if same else "conflict",
                    "detail": f"Document says {doc_date.value}, registry says {record['registered']}",
                    "source": "MCA Company Master Data", "kind": "dataset",
                })
        else:
            out.append({"check": "cin_in_registry", "status": "conflict",
                        "detail": f"{cin.value} is not in the MCA registry",
                        "source": "MCA Company Master Data", "kind": "dataset"})

    gstin = by_key.get("gstin")
    if gstin:
        decoded = decode_gstin(str(gstin.value))
        out.append({
            "check": "gstin_checksum",
            "status": "verified" if decoded["valid"] else "conflict",
            "detail": (f"Valid · {decoded['state']} · PAN holder {decoded['pan_holder']}"
                       if decoded["valid"] else decoded.get("error", "invalid")),
            "source": "GSTIN check digit", "kind": "local",
        })
        if decoded["valid"] and by_key.get("pan"):
            same = decoded["pan"] == str(by_key["pan"].value)
            out.append({"check": "pan_matches_gstin", "status": "verified" if same else "conflict",
                        "detail": f"PAN {by_key['pan'].value} {'matches' if same else 'differs from'} the GSTIN's embedded PAN",
                        "source": "GSTIN check digit", "kind": "local"})

    if startup is not None:
        if cin and startup.cin and str(cin.value) != startup.cin:
            out.append({"check": "cin_matches_profile", "status": "conflict",
                        "detail": f"The profile says {startup.cin}, this document says {cin.value}",
                        "source": "This profile", "kind": "local"})
        revenue = by_key.get("revenue")
        financials = startup.latest_financials
        if revenue and financials and financials.revenue:
            claimed, found = float(financials.revenue), float(revenue.value)
            gap = abs(claimed - found) / max(claimed, 1)
            out.append({
                "check": "revenue_matches_profile",
                "status": "verified" if gap <= 0.2 else "conflict",
                "detail": f"Document shows {found:,.0f}; the profile reports {claimed:,.0f} ({gap:.0%} apart)",
                "source": "This profile", "kind": "local",
            })
    return out
