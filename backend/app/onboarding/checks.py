"""Deterministic checks and value comparison.

Nothing here calls the network. The CIN and GSTIN decoders are real: both
identifiers encode facts (state, incorporation year, company type, PAN) that
can be cross-checked against what the founder and the website say, and the
GSTIN carries a check digit that catches typos and invented numbers.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Literal

Verdict = Literal["agree", "disagree", "neutral"]

# --------------------------------------------------------------------------
# Indian identifiers
# --------------------------------------------------------------------------

CIN_RE = re.compile(r"^([LU])(\d{5})([A-Z]{2})(\d{4})([A-Z]{3})(\d{6})$")
GSTIN_RE = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")

CIN_STATES = {
    "AP": "Andhra Pradesh", "AS": "Assam", "BR": "Bihar", "CH": "Chandigarh",
    "CT": "Chhattisgarh", "DL": "Delhi", "GA": "Goa", "GJ": "Gujarat",
    "HR": "Haryana", "HP": "Himachal Pradesh", "JH": "Jharkhand", "JK": "Jammu and Kashmir",
    "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh", "MH": "Maharashtra",
    "OR": "Odisha", "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan",
    "TN": "Tamil Nadu", "TG": "Telangana", "TS": "Telangana", "UP": "Uttar Pradesh",
    "UR": "Uttarakhand", "WB": "West Bengal",
}
CIN_TYPES = {
    "PTC": "Private limited", "PLC": "Public limited", "OPC": "One person company",
    "FTC": "Subsidiary of a foreign company", "GOI": "Government company",
    "NPL": "Not-for-profit (Section 8)", "ULL": "Unlimited liability",
}
GST_STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan",
    "09": "Uttar Pradesh", "10": "Bihar", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "36": "Telangana",
    "37": "Andhra Pradesh",
}
PAN_HOLDER = {
    "C": "Company", "P": "Individual", "F": "Firm / LLP", "H": "HUF", "A": "AOP",
    "T": "Trust", "B": "BOI", "L": "Local authority", "J": "Artificial juridical person",
    "G": "Government",
}


LLPIN_RE = re.compile(r"^[A-Z]{3}-\d{4}$")


def decode_cin(raw: str) -> dict[str, Any]:
    cin = re.sub(r"\s", "", raw or "").upper()
    if LLPIN_RE.match(cin):
        # LLPs get an LLPIN instead of a CIN; it encodes nothing beyond identity.
        return {"valid": True, "cin": cin, "listed": False, "industry_code": None, "state_code": None,
                "state": None, "incorporation_year": None, "company_type": "Limited liability partnership",
                "registration_number": cin}
    m = CIN_RE.match(cin)
    if not m:
        return {
            "valid": False,
            "cin": cin,
            "error": "Expected a 21-character CIN like U72900KA2019PTC123456 (or an LLPIN like AAB-1234)",
        }
    listing, industry, state, year, kind, reg = m.groups()
    return {
        "valid": True,
        "cin": cin,
        "listed": listing == "L",
        "industry_code": industry,
        "state_code": state,
        "state": CIN_STATES.get(state),
        "incorporation_year": int(year),
        "company_type": CIN_TYPES.get(kind, kind),
        "registration_number": reg,
    }


_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _GST_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def decode_gstin(raw: str) -> dict[str, Any]:
    gstin = re.sub(r"\s", "", raw or "").upper()
    m = GSTIN_RE.match(gstin)
    if not m:
        return {"valid": False, "gstin": gstin, "error": "Expected 15 characters like 29ABCDE1234F1Z5"}
    expected = gstin_check_digit(gstin[:14])
    state_code, pan, entity, _check = m.groups()
    if expected != gstin[14]:
        return {
            "valid": False,
            "gstin": gstin,
            "error": f"Check digit is {gstin[14]} but should be {expected} — likely a typo",
        }
    return {
        "valid": True,
        "gstin": gstin,
        "state_code": state_code,
        "state": GST_STATES.get(state_code),
        "pan": pan,
        "pan_holder": PAN_HOLDER.get(pan[3], "Unknown"),
        "registration_in_state": entity,
    }


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

_SUFFIXES = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|incorporated|llc|corp|corporation|co|gmbh|plc)\b\.?",
    re.I,
)

CITY_ALIASES = {
    "bangalore": "bengaluru", "bengaluru": "bengaluru", "bombay": "mumbai",
    "gurgaon": "gurugram", "gurugram": "gurugram", "new delhi": "delhi",
    "madras": "chennai", "calcutta": "kolkata", "sf": "san francisco",
    "nyc": "new york", "new york city": "new york", "cochin": "kochi",
    "trivandrum": "thiruvananthapuram",
}

CITY_STATE = {
    "bengaluru": "Karnataka", "mysuru": "Karnataka", "mumbai": "Maharashtra",
    "pune": "Maharashtra", "delhi": "Delhi", "gurugram": "Haryana", "noida": "Uttar Pradesh",
    "hyderabad": "Telangana", "chennai": "Tamil Nadu", "kolkata": "West Bengal",
    "ahmedabad": "Gujarat", "jaipur": "Rajasthan", "kochi": "Kerala",
    "thiruvananthapuram": "Kerala", "chandigarh": "Chandigarh", "indore": "Madhya Pradesh",
    "bhubaneswar": "Odisha", "coimbatore": "Tamil Nadu", "goa": "Goa",
}

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "me.com", "proton.me", "protonmail.com", "rediffmail.com",
    "aol.com", "zoho.com", "yandex.com", "gmx.com",
}

_MULTI_PART_TLDS = {"co.in", "org.in", "net.in", "firm.in", "gen.in", "ind.in", "co.uk",
                    "org.uk", "com.au", "com.sg", "co.jp", "com.br"}


def norm_text(v: Any) -> str:
    s = _SUFFIXES.sub(" ", str(v or "").lower())
    return re.sub(r"[^a-z0-9]+", "", s)


def canon_city(v: Any) -> str:
    s = str(v or "").split(",")[0].strip().lower()
    return CITY_ALIASES.get(s, s)


def registrable_domain(host_or_url: str) -> str:
    host = (host_or_url or "").strip().lower()
    host = re.sub(r"^[a-z]+://", "", host).split("/")[0].split(":")[0]
    host = host.removeprefix("www.")
    labels = [p for p in host.split(".") if p]
    if len(labels) >= 3 and ".".join(labels[-2:]) in _MULTI_PART_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def normalise_website(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    return raw


# --------------------------------------------------------------------------
# Comparators: does a piece of evidence support a value?
# --------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare(kind: str, claim: Any, evidence: Any) -> Verdict:
    if kind == "freeform" or claim in (None, "") or evidence in (None, ""):
        return "neutral"  # prose can't be verified, only chosen between

    if kind == "name":
        a, b = norm_text(claim), norm_text(evidence)
        if not a or not b:
            return "neutral"
        if a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)):
            return "agree"
        return "agree" if SequenceMatcher(None, a, b).ratio() >= 0.85 else "disagree"

    if kind == "year":
        a, b = _num(claim), _num(evidence)
        if a is None or b is None:
            return "neutral"
        return "agree" if abs(a - b) <= 1 else "disagree"

    if kind == "domain_year":
        # Domains are often bought before a company exists, so an older domain
        # says nothing. One registered years AFTER the claimed founding does.
        founded, domain = _num(claim), _num(evidence)
        if founded is None or domain is None:
            return "neutral"
        if domain > founded + 2:
            return "disagree"
        return "agree" if domain >= founded - 3 else "neutral"

    if kind == "city":
        return "agree" if canon_city(claim) == canon_city(evidence) else "disagree"

    if kind == "state":
        return "agree" if norm_text(claim) == norm_text(evidence) else "disagree"

    if kind == "count":
        a, b = _num(claim), _num(evidence)
        if not a or not b:
            return "neutral"
        return "agree" if max(a, b) / min(a, b) <= 2.0 else "disagree"

    if kind == "money":
        a, b = _num(claim), _num(evidence)
        if not a or not b:
            return "neutral"
        return "agree" if abs(a - b) / a <= 0.2 else "disagree"

    if kind == "domain":
        return "agree" if registrable_domain(str(claim)) == registrable_domain(str(evidence)) else "disagree"

    # exact / categorical
    return "agree" if norm_text(claim) == norm_text(evidence) else "disagree"
