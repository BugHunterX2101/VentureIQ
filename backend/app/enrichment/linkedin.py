"""Founder LinkedIn insights through a third-party RapidAPI provider.

Provenance, stated plainly: this is a commercial aggregator that scrapes
LinkedIn. LinkedIn's terms prohibit scraping, so this is *not* the consented
OAuth flow or licensed partnership that `data/raw/README.md` describes as the
lawful path. It is therefore:

  - off by default (no `VIQ_RAPIDAPI_KEY`, no calls);
  - recorded with `source="linkedin"`, `is_mock=False`, and a `_provenance`
    field naming the aggregator, so the profile never implies LinkedIn itself
    confirmed anything;
  - used to corroborate a founder's own claim (their name, their current
    company), never to mark a company field verified.

The response shape of these providers changes without notice, so the parser
below reads defensively and keeps the raw payload. `scripts/check_linkedin.py`
prints both, which is how you check a provider still matches.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings

PROVENANCE = "third-party aggregator (scraped LinkedIn data), not LinkedIn's own API"

_EXPERIENCE_KEYS = ("experiences", "experience", "positions", "position",
                    "workExperience", "work_experience", "position_groups")
_EDUCATION_KEYS = ("educations", "education", "schools", "education_history")
_FOUNDER_TITLE = re.compile(r"\b(founder|co-?founder|cofounder)\b", re.I)
_EXIT_HINT = re.compile(r"\b(acquired|acquisition|exited|exit|ipo|merged)\b", re.I)


def enabled() -> bool:
    return bool(settings.rapidapi_key)


def handle_from(url_or_handle: str | None) -> str | None:
    """'https://linkedin.com/in/foo/' or '@foo' or 'foo' → 'foo'."""
    if not url_or_handle:
        return None
    s = str(url_or_handle).strip().rstrip("/")
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?#]+)", s, re.I)
    if m:
        return m.group(1)
    if "linkedin.com" in s.lower():
        return None  # a company page or something else, not a person
    return s.lstrip("@") or None


class QuotaExceeded(RuntimeError):
    """The monthly RapidAPI budget is spent; refuse rather than overspend."""


# --------------------------------------------------------------------------
# cache — the provider's free tier is 50 calls a month, so every response is
# kept and reused. Cached profiles cost nothing and work offline.
# --------------------------------------------------------------------------

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS linkedin_profile (
    handle TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    raw TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
    provider TEXT NOT NULL,
    month TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, month)
);
"""


def _cache() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.cache_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CACHE_SCHEMA)
    return conn


def _this_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def usage(provider: str = "rapidapi") -> dict[str, Any]:
    conn = _cache()
    try:
        row = conn.execute("SELECT calls FROM api_usage WHERE provider = ? AND month = ?",
                           (provider, _this_month())).fetchone()
        cached = conn.execute("SELECT COUNT(*) FROM linkedin_profile").fetchone()[0]
    finally:
        conn.close()
    used = row["calls"] if row else 0
    return {"month": _this_month(), "calls_used": used,
            "budget": settings.rapidapi_monthly_budget,
            "remaining": max(0, settings.rapidapi_monthly_budget - used),
            "profiles_cached": cached}


def cached_profile(handle: str, max_age_days: int | None = None) -> dict[str, Any] | None:
    max_age = settings.linkedin_cache_days if max_age_days is None else max_age_days
    conn = _cache()
    try:
        row = conn.execute("SELECT fetched_at, raw FROM linkedin_profile WHERE handle = ?",
                           (handle,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    age = datetime.now(UTC) - datetime.fromisoformat(row["fetched_at"])
    if age.days > max_age:
        return None
    return json.loads(row["raw"])


def _store(handle: str, raw: dict[str, Any]) -> None:
    conn = _cache()
    try:
        conn.execute("INSERT OR REPLACE INTO linkedin_profile (handle, fetched_at, raw) VALUES (?, ?, ?)",
                     (handle, datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(raw)))
        conn.execute("""INSERT INTO api_usage (provider, month, calls) VALUES ('rapidapi', ?, 1)
                        ON CONFLICT(provider, month) DO UPDATE SET calls = calls + 1""", (_this_month(),))
        conn.commit()
    finally:
        conn.close()


async def fetch_profile(handle: str, *, refresh: bool = False) -> dict[str, Any]:
    """Cached provider payload for one profile. Raises httpx.HTTPError.

    Set `refresh` to bypass the cache; that spends one call from the monthly
    quota. `last_source` on the returned dict says where it came from.
    """
    if not refresh:
        hit = cached_profile(handle)
        if hit is not None:
            if hit.get("_not_found"):
                raise httpx.HTTPStatusError(
                    "cached 404",
                    request=httpx.Request("GET", "https://cached"),
                    response=httpx.Response(404),
                )
            hit["_cache"] = "hit"
            return hit
    if not enabled():
        raise RuntimeError("VIQ_RAPIDAPI_KEY is not set")
    left = usage()["remaining"]
    if left <= 0:
        raise QuotaExceeded(
            f"monthly budget of {settings.rapidapi_monthly_budget} RapidAPI calls is spent; "
            "cached profiles still work"
        )
    host = settings.linkedin_api_host
    async with httpx.AsyncClient(timeout=25) as client:
        res = await client.get(
            f"https://{host}{settings.linkedin_api_path}",
            params={settings.linkedin_api_param: handle},
            headers={"x-rapidapi-key": settings.rapidapi_key, "x-rapidapi-host": host},
        )
    if res.status_code == 404:
        # Cache the miss too: a handle that does not exist must not be paid for
        # again on every retry.
        _store(handle, {"_not_found": True, "status": 404})
        res.raise_for_status()
    res.raise_for_status()
    raw = res.json()
    _store(handle, raw)
    raw["_cache"] = "miss"
    return raw


# --------------------------------------------------------------------------
# parsing — tolerant, because provider shapes differ and drift
# --------------------------------------------------------------------------


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _first(raw: Any, *names: str) -> Any:
    for node in _walk(raw):
        for n in names:
            v = node.get(n)
            if isinstance(v, (str, int, float)) and str(v).strip():
                return v
    return None


def _list_of_dicts(raw: Any, names: tuple[str, ...]) -> list[dict]:
    for node in _walk(raw):
        for n in names:
            v = node.get(n)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                return v
    return []


def _years(*texts: Any) -> list[int]:
    out: list[int] = []
    for t in texts:
        out += [int(y) for y in re.findall(r"(19\d{2}|20\d{2})", str(t or ""))]
    return out


def _int(v: Any) -> int | None:
    if v is None:
        return None
    m = re.search(r"\d[\d,]*", str(v))
    return int(m.group(0).replace(",", "")) if m else None


def _year(v: Any) -> int | None:
    """{'year': 2000} or '2000' or 'Jan 2000' → 2000."""
    if isinstance(v, dict):
        v = v.get("year")
    ys = _years(v)
    return ys[0] if ys else None


def _parse_linkedinfetch(raw: dict[str, Any]) -> dict[str, Any] | None:
    """linkedin-scraper27's shape: data.basic_info / experience / education."""
    d = raw.get("data") if isinstance(raw.get("data"), dict) else None
    bi = d.get("basic_info") if d and isinstance(d.get("basic_info"), dict) else None
    if not bi:
        return None

    positions = []
    for e in d.get("experience") or []:
        if not isinstance(e, dict):
            continue
        start, end = _year(e.get("start_date")), _year(e.get("end_date"))
        current = bool(e.get("is_current"))
        if not start and e.get("duration"):
            ys = _years(e["duration"])
            start, end = (ys[0] if ys else None), (None if current else (ys[-1] if len(ys) > 1 else None))
        positions.append({
            "company": (e.get("company") or None),
            "title": (e.get("title") or None),
            "start_year": start,
            "end_year": None if current else end,
            "current": current,
            "duration": e.get("duration") or None,
            "description": (e.get("description") or None),
        })

    schools = [
        {"school": e.get("school"), "degree": e.get("degree") or e.get("field_of_study") or None,
         "years": e.get("duration") or None}
        for e in (d.get("education") or []) if isinstance(e, dict) and e.get("school")
    ]

    loc = bi.get("location") if isinstance(bi.get("location"), dict) else {}
    name = bi.get("fullname") or " ".join(
        x for x in (bi.get("first_name"), bi.get("last_name")) if x) or None
    starts = [p["start_year"] for p in positions if p["start_year"]]
    career_start = min(starts) if starts else None
    current_company = next((p["company"] for p in positions if p["current"]), None)
    founder_elsewhere = [
        p for p in positions
        if p["title"] and _FOUNDER_TITLE.search(p["title"])
        and (not current_company or p["company"] != current_company)
    ]
    about = str(bi.get("about") or "")
    exits = [p for p in positions if p["description"] and _EXIT_HINT.search(p["description"])]

    return {
        "_provenance": PROVENANCE,
        "name": name,
        "headline": bi.get("headline") or None,
        "about": about[:600] or None,
        "location": loc.get("full") or loc.get("city") or None,
        "profile_url": bi.get("profile_url") or None,
        "handle": bi.get("public_identifier") or None,
        "current_company": current_company,
        "current_title": next((p["title"] for p in positions if p["current"]), None),
        "connections": _int(bi.get("connection_count")),
        "followers": _int(bi.get("follower_count")),
        "is_influencer": bool(bi.get("is_influencer")),
        "open_to_work": bool(bi.get("open_to_work")),
        "positions": positions[:12],
        "education": schools[:5],
        "career_start_year": career_start,
        "domain_experience_years": round(datetime.now(UTC).year - career_start, 1) if career_start else None,
        "prior_founder_roles": len(founder_elsewhere),
        "self_reported_exits": (len(exits) or None) if exits else (
            1 if _EXIT_HINT.search(about) else None),
        "profile_complete": bool(name and positions),
    }


def parse_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Provider payload → the founder-credibility fields the scorer reads."""
    shaped = _parse_linkedinfetch(raw)
    if shaped:
        return shaped
    # Fallback: an unknown provider shape, read as defensively as possible.
    name = _first(raw, "full_name", "fullName", "name", "profile_name") or None
    first, last = _first(raw, "first_name", "firstName"), _first(raw, "last_name", "lastName")
    if not name and (first or last):
        name = " ".join(str(x) for x in (first, last) if x)

    positions = []
    for p in _list_of_dicts(raw, _EXPERIENCE_KEYS):
        company = p.get("company") or p.get("companyName") or p.get("company_name") or p.get("organisation")
        if isinstance(company, dict):
            company = company.get("name")
        title = p.get("title") or p.get("position") or p.get("role") or p.get("job_title")
        span = " ".join(str(p.get(k, "")) for k in
                        ("date_range", "dateRange", "duration", "start_date", "starts_at",
                         "end_date", "ends_at", "startDate", "endDate", "period"))
        yrs = _years(span, p.get("start_date"), p.get("end_date"))
        current = bool(p.get("is_current") or p.get("current")) or "present" in span.lower()
        if company or title:
            positions.append({
                "company": str(company) if company else None,
                "title": str(title) if title else None,
                "start_year": min(yrs) if yrs else None,
                "end_year": None if current else (max(yrs) if yrs else None),
                "current": current,
                "description": str(p.get("description") or "")[:400] or None,
            })

    schools = []
    for e in _list_of_dicts(raw, _EDUCATION_KEYS):
        school = e.get("school") or e.get("schoolName") or e.get("name") or e.get("institute")
        if isinstance(school, dict):
            school = school.get("name")
        if school:
            schools.append({"school": str(school), "degree": str(e.get("degree") or e.get("degree_name") or "") or None})

    starts = [p["start_year"] for p in positions if p["start_year"]]
    career_start = min(starts) if starts else None
    this_year = datetime.now(UTC).year
    founder_roles = [p for p in positions if p["title"] and _FOUNDER_TITLE.search(p["title"])]
    # Profiles have no structured "exit" field, so this only counts what the
    # person wrote themselves, and it is labelled self-reported downstream.
    exit_hints = [p for p in positions
                  if p["description"] and _EXIT_HINT.search(p["description"])]

    return {
        "_provenance": PROVENANCE,
        "name": name,
        "headline": _first(raw, "headline", "sub_title", "subTitle", "occupation"),
        "location": _first(raw, "location", "geo", "locationName", "city"),
        "current_company": next((p["company"] for p in positions if p["current"]), None),
        "current_title": next((p["title"] for p in positions if p["current"]), None),
        "connections": _int(_first(raw, "connections", "connection", "connection_count", "connectionsCount")),
        "followers": _int(_first(raw, "followers", "follower_count", "followersCount")),
        "positions": positions[:12],
        "education": schools[:5],
        "career_start_year": career_start,
        "domain_experience_years": round(this_year - career_start, 1) if career_start else None,
        "prior_founder_roles": max(0, len(founder_roles) - 1),
        "self_reported_exits": len(exit_hints) or None,
        "profile_complete": bool(name and positions),
    }


def matches(profile: dict[str, Any], founder_name: str, company: str | None) -> dict[str, Any]:
    """Does this profile look like the person who claims it, at this company?"""
    from app.onboarding.checks import compare, norm_text

    name_ok = compare("name", founder_name, profile.get("name") or "") == "agree"
    companies = [p["company"] for p in profile.get("positions", []) if p.get("company")]
    company_ok = bool(company) and any(
        compare("name", company, c) == "agree" for c in companies[:6]
    )
    headline_ok = bool(company) and norm_text(company) in norm_text(profile.get("headline") or "")
    bits = []
    if profile.get("current_title") and profile.get("current_company"):
        bits.append(f"{profile['current_title']} at {profile['current_company']}")
    if profile.get("domain_experience_years"):
        bits.append(f"{profile['domain_experience_years']:.0f} yrs since first role")
    if profile.get("connections"):
        bits.append(f"{profile['connections']:,} connections")
    return {
        "name_matches": name_ok,
        "company_matches": company_ok or headline_ok,
        "summary": " · ".join(bits) or "profile found",
    }
