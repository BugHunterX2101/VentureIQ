"""India's company registry (MCA Company Master Data, via data.gov.in).

Two ways to read it, same shape out:

  local  backend/registry.db — a bulk import of the full master data (36 lakh+
         companies) with an FTS5 index, so fuzzy name search is instant.
         Built by scripts/import_mca_registry.py.
  live   api.data.gov.in exact-match filters. Works without the import, for a
         known CIN or an exact registered name.

Source: Ministry of Corporate Affairs, "Registrars of Companies (RoC)-wise
Company Master Data", published under the Government Open Data License – India.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.onboarding.checks import CITY_ALIASES, CITY_STATE, norm_text

RESOURCE_ID = "4dbe5667-7b6b-41d7-82af-211562424d9a"
API_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
# Published on data.gov.in's own API docs; capped at 10 records per call.
SAMPLE_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
SOURCE_NOTE = "MCA Company Master Data (data.gov.in, GODL-India)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS company (
    cin TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT,
    class TEXT,
    category TEXT,
    sub_category TEXT,
    authorized_capital REAL,
    paidup_capital REAL,
    registered TEXT,          -- ISO date
    state TEXT,
    roc TEXT,
    address TEXT,
    city TEXT,                -- derived from the address
    nic_code TEXT,
    industry TEXT,
    listed TEXT,
    is_llp INTEGER
);
CREATE INDEX IF NOT EXISTS company_registered ON company(registered);
CREATE INDEX IF NOT EXISTS company_state ON company(state);
-- Prefix search (typeahead) is a range scan over this; see search_local.
CREATE INDEX IF NOT EXISTS company_name_nocase ON company(name COLLATE NOCASE);
CREATE VIRTUAL TABLE IF NOT EXISTS company_fts USING fts5(
    name, content='company', content_rowid='rowid', tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Cities we can recognise inside a free-text registered-office address.
_CITIES = sorted(
    set(CITY_STATE) | set(CITY_ALIASES) | {
        "ahmedabad", "surat", "vadodara", "rajkot", "nagpur", "nashik", "thane", "navi mumbai",
        "lucknow", "kanpur", "ghaziabad", "faridabad", "ludhiana", "mohali", "dehradun",
        "patna", "ranchi", "raipur", "bhopal", "gwalior", "visakhapatnam", "vijayawada",
        "guntur", "madurai", "tiruchirappalli", "mangaluru", "mangalore", "hubli", "belgaum",
        "thrissur", "kozhikode", "calicut", "guwahati", "jodhpur", "udaipur", "varanasi",
        "agra", "meerut", "amritsar", "jalandhar", "vellore", "salem", "tirupur", "erode",
        "puducherry", "secunderabad", "howrah", "durgapur", "siliguri", "cuttack", "jammu",
        "srinagar", "shimla", "panaji", "aurangabad", "solapur", "kolhapur", "new delhi",
    },
    key=len,
    reverse=True,
)
_CITY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in _CITIES) + r")\b", re.I)

_lock = threading.Lock()


def db_path() -> Path:
    return Path(settings.registry_db_path)


def connect(write: bool = False) -> sqlite3.Connection:
    path = db_path()
    if not write and not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if write:
        conn.executescript(SCHEMA)
    return conn


def city_from_address(address: str | None) -> str | None:
    if not address:
        return None
    hits = _CITY_RE.findall(address)
    if not hits:
        return None
    city = hits[-1].lower()  # the city usually sits near the end, before state/PIN
    city = CITY_ALIASES.get(city, city)
    return city.title()


def _money(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalise_record(r: dict[str, Any]) -> dict[str, Any]:
    """One API record → one `company` row."""
    cin = (r.get("CIN") or "").strip().upper()
    state = (r.get("CompanyStateCode") or "").strip()
    return {
        "cin": cin,
        "name": (r.get("CompanyName") or "").strip(),
        "status": (r.get("CompanyStatus") or "").strip() or None,
        "class": (r.get("CompanyClass") or "").strip() or None,
        "category": (r.get("CompanyCategory") or "").strip() or None,
        "sub_category": (r.get("CompanySubCategory") or "").strip() or None,
        "authorized_capital": _money(r.get("AuthorizedCapital")),
        "paidup_capital": _money(r.get("PaidupCapital")),
        "registered": (r.get("CompanyRegistrationdate_date") or "")[:10] or None,
        "state": state.title() if state else None,
        "roc": (r.get("CompanyROCcode") or "").strip() or None,
        "address": (r.get("Registered_Office_Address") or "").strip() or None,
        "city": city_from_address(r.get("Registered_Office_Address")),
        "nic_code": (r.get("nic_code") or "").strip() or None,
        "industry": (r.get("CompanyIndustrialClassification") or "").strip() or None,
        "listed": (r.get("Listingstatus") or "").strip() or None,
        "is_llp": 0 if re.match(r"^[LU]\d{5}", cin) else 1,
    }


# --------------------------------------------------------------------------
# local store
# --------------------------------------------------------------------------


def available() -> bool:
    try:
        with _lock:
            conn = connect()
            try:
                return conn.execute("SELECT 1 FROM company LIMIT 1").fetchone() is not None
            finally:
                conn.close()
    except (FileNotFoundError, sqlite3.Error):
        return False


def stats() -> dict[str, Any]:
    if not db_path().exists():
        return {"available": False, "companies": 0, "source": SOURCE_NOTE}
    conn = connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        return {"available": False, "companies": 0, "source": SOURCE_NOTE}
    finally:
        conn.close()
    return {
        "available": n > 0,
        "companies": n,
        "source_total": int(meta["source_total"]) if meta.get("source_total") else None,
        "source_updated": meta.get("source_updated"),
        "imported_at": meta.get("imported_at"),
        "complete": meta.get("complete") == "1",
        "source": SOURCE_NOTE,
    }


def _row(r: sqlite3.Row) -> dict[str, Any]:
    return {k: r[k] for k in r.keys() if k != "rowid"}


def get_local(cin: str) -> dict[str, Any] | None:
    try:
        conn = connect()
    except FileNotFoundError:
        return None
    try:
        r = conn.execute("SELECT * FROM company WHERE cin = ?", (cin.strip().upper(),)).fetchone()
        return _row(r) if r else None
    finally:
        conn.close()


def _fts_query(q: str) -> str | None:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", q) if w.lower() not in {
        "private", "pvt", "limited", "ltd", "llp", "the", "and", "of", "india"}]
    if not words:
        return None
    # Every word must appear; the last one may be a prefix (typeahead).
    return " ".join(f'"{w}"' for w in words[:-1]) + f' "{words[-1]}"*'


def _ensure_prefix_index(conn: sqlite3.Connection) -> None:
    """A case-insensitive index on the name, so typeahead is a range scan.

    FTS5 has to score every match before it can order them, which is slow once
    a prefix matches thousands of companies. Prefix queries answer from this
    index instead, and FTS is kept for word matches inside a name.
    """
    conn.execute("CREATE INDEX IF NOT EXISTS company_name_nocase ON company(name COLLATE NOCASE)")


def search_local(
    q: str,
    limit: int = 20,
    state: str | None = None,
    active_only: bool = False,
    since: str | None = None,
) -> list[dict[str, Any]]:
    fts = _fts_query(q)
    if not fts:
        return []
    try:
        conn = connect()
    except FileNotFoundError:
        return []

    def filters(sql: str, args: list[Any]) -> tuple[str, list[Any]]:
        if state:
            sql += " AND c.state = ?"
            args.append(state.title())
        if active_only:
            sql += " AND c.status = 'Active'"
        if since:
            sql += " AND c.registered >= ?"
            args.append(since)
        return sql, args

    want = max(limit * 3, 30)
    rows: list[dict[str, Any]] = []
    try:
        # 1. What the typeahead almost always wants: names starting with the query.
        _ensure_prefix_index(conn)
        # No ESCAPE clause: it would stop SQLite using the index for LIKE 'x%',
        # so wildcards are stripped from the query instead.
        prefix_sql, prefix_args = filters(
            "SELECT c.* FROM company c WHERE c.name LIKE ?",
            [re.sub(r"[%_]", " ", q.strip()) + "%"],
        )
        prefix_sql += " LIMIT ?"
        prefix_args.append(want)
        rows = [_row(r) for r in conn.execute(prefix_sql, prefix_args).fetchall()]

        # 2. Top up with word matches from anywhere in the name.
        if len(rows) < want:
            seen = {r["cin"] for r in rows}
            fts_sql, fts_args = filters(
                "SELECT c.*, bm25(company_fts) AS rank FROM company_fts "
                "JOIN company c ON c.rowid = company_fts.rowid WHERE company_fts MATCH ?",
                [fts],
            )
            fts_sql += " ORDER BY rank LIMIT ?"
            fts_args.append(want)
            rows += [r for r in (_row(x) for x in conn.execute(fts_sql, fts_args).fetchall())
                     if r["cin"] not in seen]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    # Re-rank: exact normalised-name matches and active companies first.
    key = norm_text(q)
    rows.sort(key=lambda r: (
        norm_text(r["name"]) != key,
        not norm_text(r["name"]).startswith(key),
        r["status"] != "Active",
        len(r["name"]),
    ))
    for r in rows:
        r.pop("rank", None)
    return rows[:limit]


# --------------------------------------------------------------------------
# live (data.gov.in API, exact filters)
# --------------------------------------------------------------------------


def api_key() -> str:
    return settings.data_gov_in_key or SAMPLE_KEY


async def fetch_live(filters: dict[str, str], limit: int = 10) -> list[dict[str, Any]]:
    params = {"api-key": api_key(), "format": "json", "limit": str(limit)}
    params.update({f"filters[{k}]": v for k, v in filters.items()})
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "VentureIQ/0.1"}) as client:
        res = await client.get(API_URL, params=params)
    res.raise_for_status()
    return [normalise_record(r) for r in res.json().get("records", [])]


async def lookup_cin(cin: str) -> tuple[dict[str, Any] | None, str]:
    """(record, how) — local first, then the live API."""
    local = get_local(cin)
    if local:
        return local, "local"
    rows = await fetch_live({"CIN": cin.strip().upper()}, limit=1)
    return (rows[0] if rows else None), "live"


def name_variants(name: str) -> list[str]:
    """Registered names are upper-case with a legal suffix; guess the usual ones."""
    base = re.sub(r"\s+", " ", re.sub(r"(?i)\b(pvt\.?|private|ltd\.?|limited|llp)\b", "", name)).strip().upper()
    if not base:
        return []
    out = [f"{base} PRIVATE LIMITED", f"{base} LIMITED", f"{base} TECHNOLOGIES PRIVATE LIMITED",
           f"{base} LLP", base]
    return list(dict.fromkeys(out))
