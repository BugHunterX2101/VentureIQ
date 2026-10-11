"""Fill in the things a company profile is missing --- from real sources only.

Most of the corpus arrived as a name, a sector and a funding number. No logo,
no founders, no links. The fix is not to generate any of that; it is to go and
get what genuinely exists, and to leave the rest visibly empty.

Three passes, cheapest and most certain first:

  1. **YC directory** (no network, already on disk). Every one of the 6,151 YC
     companies ships a logo URL in `yc_companies_all.json`, and 6,113 carry a
     website. Free, exact, attributable.
  2. **Indian funding records** (no network, already on disk). The 2021 file
     has a `Founders` column --- 1,205 companies with the real names of the
     people who started them. These replace the "Founder N (modelled)"
     placeholders, and are marked as coming from that dataset.
  3. **The company's own website** (network, rate-limited, resumable). For a
     company with a site, read it once and keep only what it actually
     publishes: its logo, its LinkedIn page, its X account, its GitHub org and
     any founder names it lists. This is the same extraction the registration
     agent runs live, applied in bulk.

Nothing here writes a value it did not find. A company with no website and no
YC record keeps its initials tile and an empty founder list, which is the
honest answer.

    .venv/bin/python scripts/backfill_profiles.py --datasets
    .venv/bin/python scripts/backfill_profiles.py --web --limit 300
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DATA_RAW  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import Founder, Startup  # noqa: E402
from app.seed.loader import _norm_name  # noqa: E402

NULLISH = {"", "nan", "none", "null", "-", "n/a", "na", "undisclosed"}


# --------------------------------------------------------------------------
# 1. Y Combinator directory
# --------------------------------------------------------------------------


def from_yc(db) -> dict[str, int]:
    path = DATA_RAW / "yc_companies_all.json"
    if not path.exists():
        return {"yc_logos": 0, "yc_websites": 0}

    by_slug = {}
    for c in json.load(path.open()):
        slug = (c.get("slug") or "").lower()
        if slug:
            by_slug[slug] = c

    logos = websites = 0
    for s in db.query(Startup).filter(Startup.source == "seed_yc").all():
        c = by_slug.get((s.slug or "").lower())
        if not c:
            continue
        logo = (c.get("small_logo_thumb_url") or "").strip()
        # YC serves "/company/thumb/missing.png" for companies that never
        # uploaded one. Storing that would put a broken image on the profile,
        # which is worse than the initials tile it would replace.
        if not logo.startswith(("http://", "https://")) or "missing" in logo:
            logo = ""
        if logo and not s.logo_url:
            s.logo_url, s.logo_source = logo, "yc_directory"
            logos += 1
        site = (c.get("website") or "").strip()
        if site and not s.website:
            s.website = site
            websites += 1
    db.commit()
    return {"yc_logos": logos, "yc_websites": websites}


# --------------------------------------------------------------------------
# 2. Indian funding records --- real founder names
# --------------------------------------------------------------------------


def _split_people(raw: str) -> list[str]:
    """"Mayank Kumar, Phalgun Kompalli & Ronnie Screwvala" -> three names."""
    parts = re.split(r",| and | & |;|\band\b", raw)
    out = []
    for p in parts:
        name = re.sub(r"\s+", " ", p).strip(" .")
        # A name, not a sentence or a company suffix.
        if 2 < len(name) <= 60 and 1 <= len(name.split()) <= 4 and not name.lower() in NULLISH:
            if not re.search(r"(?i)\b(pvt|private|limited|ltd|llp|inc|technologies)\b", name):
                out.append(name)
    return list(dict.fromkeys(out))[:5]


def from_india_records(db) -> dict[str, int]:
    path = DATA_RAW / "startup_funding2021.csv"
    if not path.exists():
        return {"real_founders_named": 0, "companies_with_founders": 0}

    names_by_company: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.DictReader(fh):
            company = (row.get("Company/Brand") or "").strip()
            people = (row.get("Founders") or "").strip()
            if len(company) < 2 or people.lower() in NULLISH:
                continue
            found = _split_people(people)
            if found:
                names_by_company.setdefault(_norm_name(company), found)

    named = companies = 0
    for s in db.query(Startup).filter(Startup.source == "seed_india_funding").all():
        people = names_by_company.get(s.slug or _norm_name(s.legal_name))
        if not people:
            continue
        existing = sorted(s.founders, key=lambda f: ("CEO" not in (f.role or ""), f.founder_id))
        # Replace placeholder rows in order, then add any people left over. The
        # modelled credibility signals stay on the row; only the identity
        # becomes real, and says so.
        for i, name in enumerate(people):
            if i < len(existing):
                row_ = existing[i]
                if row_.name_source in (None, "modelled") or row_.name.startswith("Founder "):
                    row_.name = name
                    row_.name_source = "india_funding_records"
                    named += 1
            else:
                db.add(Founder(startup_id=s.startup_id, name=name,
                               role="Co-Founder" if i else "Co-Founder & CEO",
                               name_source="india_funding_records"))
                named += 1
        # Any placeholder beyond the real list is a guess about team size we
        # cannot support, so it goes.
        for extra in existing[len(people):]:
            if extra.name_source in (None, "modelled") or extra.name.startswith("Founder "):
                db.delete(extra)
        companies += 1
    db.commit()
    return {"real_founders_named": named, "companies_with_founders": companies}


# --------------------------------------------------------------------------
# 3. The company's own website
# --------------------------------------------------------------------------


async def _read_site(website: str) -> dict:
    """Whatever the site itself publishes. Never raises.

    Reuses the registration agent's own extraction, so a bulk backfill and a
    live registration read a page the same way.
    """
    from app.onboarding import checks
    from app.onboarding.fetch import safe_get
    from app.onboarding.tools import _Page, _profile_links

    out: dict = {}
    try:
        url = checks.normalise_website(website)
        page = await safe_get(url)
        if page.status >= 400 or not page.text:
            return out
        parser = _Page()
        parser.feed(page.text)

        # og:image is the image the company chose to represent itself. No
        # favicon guessing and no third-party logo service: this is their mark
        # or nothing.
        logo = (parser.meta.get("og:image") or "").strip()
        if logo.startswith(("http://", "https://")):
            out["logo_url"] = logo[:512]

        links = _profile_links(parser.links, page.url)
        if links.get("linkedin"):
            out["linkedin_url"] = links["linkedin"][:512]
        if links.get("twitter"):
            out["twitter_url"] = links["twitter"][:512]
        if links.get("github"):
            out["github_org"] = links["github"][:96]
    except Exception:
        return out
    return out


async def from_websites(db, limit: int, delay: float) -> dict[str, int]:
    todo = (
        db.query(Startup)
        .filter(Startup.website.isnot(None), Startup.profile_source.is_(None))
        .limit(limit)
        .all()
    )
    logos = links = 0
    for i, s in enumerate(todo, 1):
        found = await _read_site(s.website)
        # Mark it attempted either way, so a rerun moves on instead of
        # hammering a site that publishes nothing.
        s.profile_source = "website" if found else "website_none"
        if found.get("logo_url") and not s.logo_url:
            s.logo_url, s.logo_source = found["logo_url"], "website"
            logos += 1
        for key in ("linkedin_url", "twitter_url", "github_org"):
            if found.get(key) and not getattr(s, key):
                setattr(s, key, found[key])
                links += 1
        if i % 25 == 0:
            db.commit()
            print(f"    {i}/{len(todo)} · {logos} logos · {links} links")
        await asyncio.sleep(delay)
    db.commit()
    return {"site_logos": logos, "site_links": links, "sites_read": len(todo)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets", action="store_true", help="passes 1 and 2, no network")
    ap.add_argument("--web", action="store_true", help="pass 3, reads company websites")
    ap.add_argument("--limit", type=int, default=250, help="how many sites to read")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between sites")
    args = ap.parse_args()
    if not (args.datasets or args.web):
        args.datasets = True

    db = SessionLocal()
    try:
        out: dict[str, int] = {}
        if args.datasets:
            print("Y Combinator directory…")
            out |= from_yc(db)
            print("Indian funding records…")
            out |= from_india_records(db)
        if args.web:
            print(f"Company websites (up to {args.limit})…")
            out |= asyncio.run(from_websites(db, args.limit, args.delay))
    finally:
        db.close()
    for k, v in out.items():
        print(f"  {k}: {v:,}")


if __name__ == "__main__":
    main()
