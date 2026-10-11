"""GSTIN verification against the public GST taxpayer search.

What is public and what is not, precisely:

- *Taxpayer details* — legal name, trade name, status, registration date,
  constitution, state jurisdiction — are published by the GST portal's own
  "Search Taxpayer" service. Several vendors resell that as an API, which is
  what this module calls when one is configured.
- *Turnover band and filing history* are published too, but the vendor's free
  tier withholds them ("Available in Paid Version of API"). When a paid tier is
  configured, the band is parsed and used; on the free tier it is reported as
  unavailable, never shown as data.
- *Exact turnover and return contents* are private to the taxpayer, lawfully
  obtainable only with per-pull consent through a GST Suvidha Provider. That
  part of revenue reconciliation stays a clearly-labelled simulation.

Configure a vendor with VIQ_GST_API_HOST/PATH/PARAM. RapidAPI hosts use
VIQ_GST_RETURN_STATUS_API_KEY (or the shared VIQ_RAPIDAPI_KEY). Responses are
cached, so repeat lookups cost nothing.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.enrichment.linkedin import QuotaExceeded, _cache, _this_month, usage

SOURCE = "GST taxpayer search (public register, via API vendor)"


def _needs_key(host: str) -> bool:
    return host.endswith("rapidapi.com")


def _key() -> str | None:
    return settings.gst_return_status_api_key or settings.rapidapi_key


def enabled() -> bool:
    host = settings.gst_api_host
    # RapidAPI vendors need a key; a vendor's own endpoint may not.
    return bool(host and (_key() or not _needs_key(host)))


def _store(gstin: str, raw: dict[str, Any], metered: bool = True) -> None:
    conn = _cache()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS gst_profile (
                   gstin TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, raw TEXT NOT NULL)"""
        )
        conn.execute("INSERT OR REPLACE INTO gst_profile (gstin, fetched_at, raw) VALUES (?, ?, ?)",
                     (gstin, datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(raw)))
        if metered:
            conn.execute("""INSERT INTO api_usage (provider, month, calls) VALUES ('rapidapi', ?, 1)
                            ON CONFLICT(provider, month) DO UPDATE SET calls = calls + 1""", (_this_month(),))
        conn.commit()
    finally:
        conn.close()


def cached(gstin: str) -> dict[str, Any] | None:
    conn = _cache()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS gst_profile (
                   gstin TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, raw TEXT NOT NULL)"""
        )
        row = conn.execute("SELECT raw FROM gst_profile WHERE gstin = ?", (gstin,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return json.loads(row["raw"]) if row else None


async def fetch(gstin: str, *, refresh: bool = False) -> dict[str, Any]:
    """Raw vendor payload for one GSTIN, cached. Raises httpx.HTTPError."""
    gstin = gstin.strip().upper()
    if not refresh:
        hit = cached(gstin)
        if hit is not None:
            hit["_cache"] = "hit"
            return hit
    if not enabled():
        raise RuntimeError("No GST API configured (VIQ_GST_API_HOST / VIQ_RAPIDAPI_KEY)")
    host = settings.gst_api_host
    # Only metered vendors come out of the monthly budget.
    if _needs_key(host) and usage()["remaining"] <= 0:
        raise QuotaExceeded("the monthly API budget is spent; cached lookups still work")

    url = f"https://{host}{settings.gst_api_path}"
    params = {settings.gst_api_param: gstin} if settings.gst_api_param else {}
    if "{gstin}" in settings.gst_api_path:
        url = f"https://{host}{settings.gst_api_path.replace('{gstin}', gstin)}"
        params = {}
    headers = {"User-Agent": "VentureIQ-Verifier/0.1"}
    if _needs_key(host):
        headers |= {"x-rapidapi-key": _key() or "", "x-rapidapi-host": host}
    async with httpx.AsyncClient(timeout=25) as client:
        res = await client.get(url, params=params, headers=headers)
    res.raise_for_status()
    raw = res.json()
    _store(gstin, raw, metered=_needs_key(host))
    raw["_cache"] = "miss"
    return raw


# --------------------------------------------------------------------------
# parsing — vendors differ, so read defensively and keep the raw payload
# --------------------------------------------------------------------------

_KEYS = {
    "legal_name": ("lgnm", "legal_name", "legalName", "legal_name_of_business", "name"),
    "trade_name": ("tradeNam", "trade_name", "tradeName", "tradenam"),
    "status": ("sts", "status", "gstin_status", "registration_status"),
    "registration_date": ("rgdt", "registration_date", "registrationDate", "date_of_registration"),
    "constitution": ("ctb", "constitution", "constitution_of_business", "business_constitution"),
    "taxpayer_type": ("dty", "taxpayer_type", "taxpayerType", "dealer_type"),
    "state": ("stj", "state_jurisdiction", "state", "stateJurisdiction"),
    "pan": ("pan", "panNo", "pan_number"),
    "trade_category": ("compCategory", "compliance_category"),
    "cancelled_on": ("cxdt", "cancellation_date"),
    "address": ("adr", "address", "principal_address"),
    "pincode": ("pincode",),
    "turnover_slab": ("aggreTurnOver", "aggregate_turnover"),
    "turnover_fy": ("aggreTurnOverFY", "aggregate_turnover_fy"),
    "einvoice_mandated": ("mandatedeInvoice",),
}


def _turnover_range_inr(slab: str | None) -> tuple[float | None, float | None]:
    """'Rs. 5 Cr. to 25 Cr.' → (5e7, 2.5e8). Open-ended slabs return None on one side.

    The GST portal publishes a *band*, never an exact figure, so this is the
    honest resolution available: a claim either falls inside the band or not.
    """
    if not slab:
        return None, None
    units = {"cr": 1e7, "crore": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5}
    numbers: list[float] = []
    for value, unit in re.findall(r"([\d,.]+)\s*(cr|crore|lakhs?|lac)?", slab, re.I):
        try:
            amount = float(value.replace(",", "").rstrip("."))
        except ValueError:
            continue
        numbers.append(amount * units.get((unit or "").lower(), 1))
    if not numbers:
        return None, None
    low = min(numbers)
    high = max(numbers) if len(numbers) > 1 else None
    if re.search(r"above|more than|greater", slab, re.I):
        return low, None
    if re.search(r"upto|up to|less than|below", slab, re.I) and len(numbers) == 1:
        return None, low
    return low, high


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _first(raw: Any, names: tuple[str, ...]) -> Any:
    for node in _walk(raw):
        for n in names:
            v = node.get(n)
            if isinstance(v, (str, int, float)) and str(v).strip():
                return str(v).strip()
    return None


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    for pattern, order in ((r"^(\d{2})/(\d{2})/(\d{4})$", "dmy"), (r"^(\d{4})-(\d{2})-(\d{2})$", "ymd")):
        m = re.match(pattern, value.strip())
        if m:
            a, b, c = m.groups()
            return f"{c}-{b}-{a}" if order == "dmy" else f"{a}-{b}-{c}"
    return value.strip()[:10]


def _state_name(jurisdiction: str | None) -> str | None:
    """'State - Karnataka,Division - Bengaluru' → 'Karnataka'."""
    if not jurisdiction:
        return None
    first = jurisdiction.split(",")[0]
    return re.sub(r"(?i)^\s*state\s*[-:]\s*", "", first).strip() or None


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    out = {key: _first(raw, names) for key, names in _KEYS.items()}
    # The free tier returns a placeholder string instead of the value.
    for key in ("turnover_slab", "turnover_fy"):
        if out.get(key) and re.search(r"paid version|not available|upgrade", out[key], re.I):
            out[key] = None
            out["turnover_withheld"] = True
    out["state"] = _state_name(out.get("state"))
    out["registration_date"] = _iso_date(out.get("registration_date"))
    out["active"] = (out.get("status") or "").strip().lower() in ("active", "act", "yes")

    low, high = _turnover_range_inr(out.get("turnover_slab"))
    out["turnover_min_inr"], out["turnover_max_inr"] = low, high

    # Real filing history: how recently, and how consistently, returns were filed.
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    returns = data.get("returns") if isinstance(data.get("returns"), list) else []
    out["returns_filed"] = len(returns)
    out["latest_return"] = None
    if returns:
        latest = returns[0]
        out["latest_return"] = {
            "type": latest.get("rtntype"), "period": latest.get("taxp"),
            "financial_year": latest.get("fy"), "filed_on": _iso_date(latest.get("dof")),
        }
    out["_source"] = SOURCE
    return out
