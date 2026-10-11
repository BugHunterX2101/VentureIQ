"""Check the LinkedIn provider end to end, and see exactly what we parse.

    python scripts/check_linkedin.py williamhgates
    python scripts/check_linkedin.py https://www.linkedin.com/in/williamhgates/ --raw

Prints the provider's own keys, what VentureIQ makes of them, and what the
founder check would conclude. Run this once after setting VIQ_RAPIDAPI_KEY: if
the provider changes its response shape, this is where it shows up first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.enrichment import linkedin as li  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", help="LinkedIn handle or profile URL")
    ap.add_argument("--company", default=None, help="company to match against")
    ap.add_argument("--name", default=None, help="founder name to match against")
    ap.add_argument("--raw", action="store_true", help="print the whole raw payload")
    ap.add_argument("--refresh", action="store_true", help="bypass the cache (spends one API call)")
    args = ap.parse_args()

    handle = li.handle_from(args.profile)
    print(f"host    : {settings.linkedin_api_host}{settings.linkedin_api_path}")
    print(f"handle  : {handle}")
    if not handle:
        print("Not a personal profile URL.")
        return 1
    if not li.enabled():
        print("VIQ_RAPIDAPI_KEY is not set — add it to backend/.env first.")
        return 1

    print(f"quota   : {li.usage()}")
    try:
        raw = await li.fetch_profile(handle, refresh=args.refresh)
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300]
        print(f"HTTP {exc.response.status_code}: {body}")
        if exc.response.status_code == 403:
            print("→ subscribe to the API on RapidAPI (free tier is enough to test).")
        return 1

    print(f"cache   : {'served from cache' if raw.get('_cache') == 'hit' else 'fetched live (1 call spent)'}")
    print(f"\ntop-level keys: {[k for k in raw if k != '_cache'][:12]}")
    profile = li.parse_profile(raw)
    parsed = {k: v for k, v in profile.items() if k not in ("positions", "education")}
    print("\nparsed:")
    print(json.dumps(parsed, indent=2))
    print(f"\npositions ({len(profile['positions'])}):")
    for p in profile["positions"][:6]:
        span = f"{p['start_year'] or '?'}–{'present' if p['current'] else (p['end_year'] or '?')}"
        print(f"  {span:<14} {p['title'] or '?'} @ {p['company'] or '?'}")
    print(f"education: {[e['school'] for e in profile['education']]}")

    name = args.name or profile.get("name") or ""
    print("\nfounder check:", json.dumps(li.matches(profile, name, args.company), indent=2))
    empty = [k for k, v in parsed.items() if v in (None, "", [])]
    if empty:
        print(f"\nNot found in this response: {', '.join(empty)}")
        print("If those matter, share this output and the mapping can be adjusted.")
    if args.raw:
        print("\nraw payload:")
        print(json.dumps(raw, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
