"""Import India's MCA company master data (36 lakh+ companies) into registry.db.

    python scripts/import_mca_registry.py                 # full import, resumable
    python scripts/import_mca_registry.py --max-rows 5000 # a quick sample
    python scripts/import_mca_registry.py --status        # show progress

Needs VIQ_DATA_GOV_IN_KEY in backend/.env (free from data.gov.in). The public
sample key only returns 10 rows per call, which is fine for trying the script
but would take days for the full set.

Safe to interrupt: progress is checkpointed per page, and re-running resumes.
The FTS name index is rebuilt at the end (or with --reindex).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.registry import store  # noqa: E402

COLUMNS = ["cin", "name", "status", "class", "category", "sub_category", "authorized_capital",
           "paidup_capital", "registered", "state", "roc", "address", "city", "nic_code",
           "industry", "listed", "is_llp"]
INSERT = (f"INSERT OR REPLACE INTO company ({', '.join(COLUMNS)}) "
          f"VALUES ({', '.join('?' for _ in COLUMNS)})")


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


async def fetch_page(client: httpx.AsyncClient, offset: int, limit: int) -> dict:
    params = {"api-key": store.api_key(), "format": "json", "limit": limit, "offset": offset}
    for attempt in range(6):
        try:
            res = await client.get(store.API_URL, params=params)
            if res.status_code == 429 or res.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=res.request, response=res)
            res.raise_for_status()
            return res.json()
        except (httpx.HTTPError, ValueError) as exc:
            wait = min(2 ** attempt, 30)
            print(f"  offset {offset}: {type(exc).__name__}, retrying in {wait}s", flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError(f"giving up at offset {offset}")


def rebuild_index(conn) -> None:
    print("Rebuilding the name index…", flush=True)
    t0 = time.time()
    conn.execute("INSERT INTO company_fts(company_fts) VALUES('rebuild')")
    conn.commit()
    print(f"  done in {time.time() - t0:.0f}s", flush=True)


async def run(args) -> None:
    conn = store.connect(write=True)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    if args.status:
        s = store.stats()
        print(s, "| next offset:", meta_get(conn, "next_offset", 0))
        return
    if args.reindex:
        rebuild_index(conn)
        return
    if args.restart:
        meta_set(conn, "next_offset", 0)
        meta_set(conn, "complete", 0)
        conn.commit()

    if not settings.data_gov_in_key:
        print("No VIQ_DATA_GOV_IN_KEY set — using the public sample key (10 rows per call).")

    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "VentureIQ/0.1"}) as client:
        probe = await fetch_page(client, 0, args.page_size)
        total = int(probe.get("total") or 0)
        page = len(probe.get("records", [])) or 1  # the server caps page size per key
        meta_set(conn, "source_total", total)
        meta_set(conn, "source_updated", probe.get("updated_date", ""))
        conn.commit()

        offset = int(meta_get(conn, "next_offset", 0))
        end = min(total, offset + args.max_rows) if args.max_rows else total
        print(f"Source: {total:,} companies (updated {probe.get('updated_date')}). "
              f"Page size {page}, {args.workers} workers, resuming at {offset:,}.", flush=True)

        t0, done = time.time(), 0
        while offset < end:
            offsets = [offset + i * page for i in range(args.workers) if offset + i * page < end]
            pages = await asyncio.gather(*(fetch_page(client, o, page) for o in offsets))
            rows = [
                tuple(rec[c] for c in COLUMNS)
                for p in pages for rec in map(store.normalise_record, p.get("records", []))
                if rec["cin"] and rec["name"]
            ]
            conn.executemany(INSERT, rows)
            offset = offsets[-1] + page
            meta_set(conn, "next_offset", offset)
            conn.commit()
            done += len(rows)
            rate = done / max(time.time() - t0, 1e-6)
            eta = (end - offset) / max(rate, 1e-6)
            print(f"  {min(offset, end):>9,}/{end:,}  {rate:,.0f} rows/s  eta {eta/60:,.0f} min", flush=True)
            if not any(p.get("records") for p in pages):
                break

    if offset >= total:
        meta_set(conn, "complete", 1)
    meta_set(conn, "imported_at", datetime.now(UTC).isoformat(timespec="seconds"))
    conn.commit()
    rebuild_index(conn)
    print(store.stats())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page-size", type=int, default=10000, help="rows requested per call (server may cap)")
    ap.add_argument("--workers", type=int, default=4, help="concurrent requests")
    ap.add_argument("--max-rows", type=int, default=0, help="stop after this many rows (0 = all)")
    ap.add_argument("--restart", action="store_true", help="start again from offset 0")
    ap.add_argument("--reindex", action="store_true", help="only rebuild the name index")
    ap.add_argument("--status", action="store_true", help="print progress and exit")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
