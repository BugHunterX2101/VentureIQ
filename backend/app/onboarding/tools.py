"""The tools the onboarding agent can call.

Each tool reads one source and reports *evidence* for ledger fields through
`ctx.find(...)`. Tools never decide what runs next — the planner in agent.py
does, based on what the tools discovered. That split is what lets the agent
change course per company (no website → registry by name; site links a GitHub
org → confirm it; nothing suggests an Indian entity → skip MCA21).

`kind` is shown to the founder next to every finding:
  network  a real request to a public source, made just now
  local    a real computation on data we already hold
  dataset  a public dataset we imported earlier; independent, but may be dated
  mock     a stand-in for a consent- or fee-gated source; never proof
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import func, or_

from app.core.database import SessionLocal
from app.enrichment.adapters import _seed_for
from app.models import FundingRound, Startup
from app.onboarding import checks
from app.onboarding.fetch import FetchError, api_get, robots_allows, safe_get

if TYPE_CHECKING:  # pragma: no cover
    from app.onboarding.agent import Run

TOOLS: dict[str, dict[str, str]] = {
    "website": {
        "label": "Company website", "kind": "network",
        "what": "Name, description, location, founding date, team size and profile links.",
        "how": "Checks robots.txt, then reads the homepage (and /about if the homepage is thin). "
               "Prefers schema.org Organization data over page text. 1.5 MB cap, public addresses only.",
        "consent": "A public page you pointed us to.",
    },
    "rdap": {
        "label": "Domain registry (RDAP)", "kind": "network",
        "what": "When the domain was registered, and by which registrar.",
        "how": "GET rdap.org/domain/{domain} — the ICANN-mandated successor to WHOIS.",
        "consent": "Public registry data.",
    },
    "dns": {
        "label": "DNS", "kind": "network",
        "what": "Whether the domain receives mail, and through which provider.",
        "how": "MX lookup over DNS-over-HTTPS (dns.google).",
        "consent": "Public DNS.",
    },
    "email": {
        "label": "Email domain", "kind": "network",
        "what": "Whether your email sits on the company's domain.",
        "how": "Compares domains, then looks up MX for the email domain. Mailbox ownership "
               "is confirmed by a one-time code (simulated in this build).",
        "consent": "Your own address.",
    },
    "corpus": {
        "label": "VentureIQ corpus", "kind": "dataset",
        "what": "Earlier records of this company: YC directory, Indian funding rounds, prior registrations.",
        "how": "Matches the domain, then the name, against 9k imported records.",
        "consent": "Public datasets, attributed in data/raw/README.md.",
    },
    "sector_model": {
        "label": "Sector classifier", "kind": "local",
        "what": "The most likely sector for your description.",
        "how": "TF-IDF nearest neighbours over the corpus; the 15 closest companies vote.",
        "consent": "—",
    },
    "github_org": {
        "label": "GitHub", "kind": "network",
        "what": "Your organisation's public repositories and activity.",
        "how": "Uses the org your site links to; otherwise searches by name and only accepts an "
               "org whose listed website is your domain.",
        "consent": "Public GitHub API.",
    },
    "cin_check": {
        "label": "CIN decoder", "kind": "local",
        "what": "Listing, state, incorporation year and company type encoded in the CIN.",
        "how": "Parses the 21-character identifier; no lookup.",
        "consent": "—",
    },
    "gstin_check": {
        "label": "GSTIN checksum", "kind": "local",
        "what": "Whether the GSTIN is well-formed, its state, and the PAN holder type.",
        "how": "Validates the mod-36 check digit and decodes the embedded PAN.",
        "consent": "—",
    },
    "city_state": {
        "label": "City → state", "kind": "local",
        "what": "The state a known Indian city is in.", "how": "Lookup table.", "consent": "—",
    },
    "mca21": {
        "label": "MCA company registry", "kind": "network",
        "what": "Registered name, CIN, incorporation date, status and registered office.",
        "how": "Searches the imported MCA Company Master Data (36 lakh+ companies) by name or CIN; "
               "without the import, looks a CIN up live on data.gov.in.",
        "consent": "Open government data (GODL-India).",
    },
    "gstn": {
        "label": "GST register", "kind": "network",
        "what": "Legal name, status, registration date and state for a GSTIN; and, with consent, "
               "turnover to reconcile your revenue claim.",
        "how": "Taxpayer details come from the public GST search when a vendor is configured. "
               "Turnover needs a consented pull through a GST Suvidha Provider, so that part is mocked.",
        "consent": "Public register; turnover needs your explicit consent per pull.",
    },
    "linkedin_company": {
        "label": "LinkedIn", "kind": "mock",
        "what": "Company page headcount band.",
        "how": "Production: LinkedIn's partner API with page-admin consent. Scraping breaks its "
               "terms, so this is mocked.",
        "consent": "Needs page-admin authorisation.",
    },
    "linkedin_profile": {
        "label": "LinkedIn (founder)", "kind": "network",
        "what": "A founder's headline, roles, years of experience and education.",
        "how": "Fetches the profile through a third-party RapidAPI provider and compares the name "
               "and current company with what was claimed.",
        "consent": "Third-party aggregator; needs VIQ_RAPIDAPI_KEY. Off when unset.",
    },
    "document": {
        "label": "Your documents", "kind": "network",
        "what": "CIN, GSTIN, registered name, incorporation date and revenue read off what you upload.",
        "how": "Tesseract OCR (or the PDF's own text layer), then the CIN is looked up in the MCA "
               "registry and the GSTIN check digit is validated.",
        "consent": "Only what you choose to upload.",
    },
    "github_user": {
        "label": "GitHub (founder)", "kind": "network",
        "what": "Whether a founder's GitHub handle exists and looks like them.",
        "how": "GET api.github.com/users/{handle}; compares the profile name and company.",
        "consent": "Public GitHub API.",
    },
}

INDIAN_HINT = re.compile(r"\b(india|bengaluru|bangalore|mumbai|delhi|gurugram|gurgaon|noida|"
                         r"hyderabad|chennai|pune|kolkata|ahmedabad|jaipur|kochi)\b", re.I)


class ToolError(Exception):
    pass


# --------------------------------------------------------------------------
# website
# --------------------------------------------------------------------------


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self.links: list[str] = []
        self.text: list[str] = []
        self._in: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in = "title"
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"].strip())
        elif tag == "script" and "ld+json" in a.get("type", ""):
            self._in = "jsonld"
            self.jsonld.append("")
        elif tag in ("script", "style"):
            self._in = "skip"
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag in ("title", "script", "style"):
            self._in = None

    def handle_data(self, data: str) -> None:
        if self._in == "title":
            self.title += data
        elif self._in == "jsonld":
            self.jsonld[-1] += data
        elif self._in is None and len(self.text) < 4000:
            t = data.strip()
            if t:
                self.text.append(t)


_ORG_TYPES = {"organization", "corporation", "localbusiness", "onlinebusiness", "softwarecompany",
              "ngo", "educationalorganization", "medicalorganization"}


def _org_nodes(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    stack = data if isinstance(data, list) else [data]
    out = []
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if "@graph" in node and isinstance(node["@graph"], list):
            stack.extend(node["@graph"])
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(str(t).lower() in _ORG_TYPES for t in types):
            out.append(node)
    return out


def _first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _looks_like_company_name(text: str, label: str) -> bool:
    """Is this a company's name, or the sentence its marketing team wrote?

    superops.ai titles its homepage "Autonomous IT operations platform for MSP
    and IT teams". Under 60 characters, so a length check alone let it through,
    and the agent then offered to rename the company to it. A name either looks
    like the domain, or is a couple of words that do not read as a sentence.
    """
    t = text.strip()
    if not t or len(t) > 60:
        return False
    if checks.compare("name", t, label) == "agree":
        return True
    return len(t.split()) <= 4 and not t.endswith((".", "!", "?"))


def _name_from_title(title: str, domain: str) -> str | None:
    parts = [p.strip() for p in re.split(r"\s[|–—\-:·]\s|\s[|·]\s?", title) if p.strip()]
    if not parts:
        return None
    label = domain.split(".")[0]
    scored = sorted(parts, key=lambda p: (checks.compare("name", p, label) != "agree", len(p)))
    best = scored[0]
    return best if _looks_like_company_name(best, label) else None


def _profile_links(links: list[str], base: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for href in links:
        url = urljoin(base, href)
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        path = urlsplit(url).path.strip("/")
        if host == "github.com" and path and "/" not in path and path not in ("about", "features"):
            found.setdefault("github", path)
        elif host.endswith("linkedin.com") and path.startswith("company/"):
            found.setdefault("linkedin", f"https://www.linkedin.com/{'/'.join(path.split('/')[:2])}")
        elif host in ("twitter.com", "x.com") and path and "/" not in path and path not in ("share", "intent"):
            found.setdefault("twitter", f"https://x.com/{path}")
    return found


async def website(ctx: Run, args: dict) -> dict:
    url = args["url"]
    domain = checks.registrable_domain(url)
    if not await robots_allows(url):
        raise ToolError(f"{domain}'s robots.txt asks automated agents not to read this page")
    try:
        page = await safe_get(url)
    except (FetchError, httpx.HTTPError) as exc:
        raise ToolError(f"Couldn't read {domain}: {exc}") from exc
    if page.status >= 400:
        raise ToolError(f"{domain} answered HTTP {page.status}")

    parser = _Page()
    parser.feed(page.text)
    final_domain = checks.registrable_domain(page.url)
    ctx.find("website", "website", page.url.rstrip("/"),
             note=f"Reachable (HTTP {page.status})" + ("" if final_domain == domain else f", redirects to {final_domain}"))

    orgs = [o for raw in parser.jsonld for o in _org_nodes(raw)]
    org = orgs[0] if orgs else {}
    data: dict[str, Any] = {"final_url": page.url, "jsonld_found": bool(org)}

    if org:
        name = org.get("legalName") or org.get("name")
        if isinstance(name, str):
            ctx.find("legal_name", "website_jsonld", name.strip(), note="schema.org Organization")
        desc = org.get("description")
        if isinstance(desc, str) and len(desc) > 20:
            ctx.find("long_description", "website_jsonld", desc.strip()[:2000])
        founding = str(org.get("foundingDate") or "")
        if m := re.match(r"(\d{4})", founding):
            ctx.find("founded_year", "website_jsonld", int(m.group(1)), note=f"foundingDate {founding}")
        addr = _first(org.get("address"))
        if isinstance(addr, dict):
            if addr.get("addressLocality"):
                ctx.find("hq_city", "website_jsonld", str(addr["addressLocality"]).strip())
            if addr.get("addressRegion"):
                ctx.find("hq_state", "website_jsonld", str(addr["addressRegion"]).strip())
            data["country"] = addr.get("addressCountry")
        emp = org.get("numberOfEmployees")
        if isinstance(emp, dict):
            emp = emp.get("value") or emp.get("maxValue") or emp.get("minValue")
        if isinstance(emp, (int, float, str)) and str(emp).isdigit():
            ctx.find("employee_count", "website_jsonld", int(emp))
        founders = org.get("founder") or org.get("founders") or []
        founders = founders if isinstance(founders, list) else [founders]
        names = [f.get("name") if isinstance(f, dict) else f for f in founders]
        data["founders"] = [n.strip() for n in names if isinstance(n, str) and n.strip()][:6]
        same = org.get("sameAs") or []
        parser.links.extend(same if isinstance(same, list) else [same])

    site_name = parser.meta.get("og:site_name") or _name_from_title(parser.title.strip(), final_domain)
    if site_name:
        # "CRED. not everyone gets it." → "CRED": drop a tagline after the brand.
        head = re.split(r"[.|–—:·]\s+|\s[-|]\s", site_name.strip())[0].strip()
        if head and head != site_name and checks.compare("name", head, final_domain.split(".")[0]) == "agree":
            site_name = head
        # og:site_name is as free-form as the title, so hold it to the same bar.
        if not _looks_like_company_name(site_name, final_domain.split(".")[0]):
            site_name = None
    if site_name:
        ctx.find("legal_name", "website", site_name.strip(), note="Page title / og:site_name")
    desc = parser.meta.get("description") or parser.meta.get("og:description")
    if desc:
        ctx.find("one_liner", "website", desc.strip()[:280], note="Meta description")

    text = " ".join(parser.text)
    if m := re.search(r"(?:©|&copy;|copyright)\s*(\d{4})\s*[-–]\s*\d{4}", text, re.I):
        ctx.find("founded_year", "website", int(m.group(1)),
                 note=f"Copyright range starts {m.group(1)} — a weak hint")

    links = _profile_links(parser.links, page.url)
    if links.get("linkedin"):
        ctx.find("linkedin_url", "website", links["linkedin"], note="Linked from your site")
    if links.get("twitter"):
        ctx.find("twitter_url", "website", links["twitter"], note="Linked from your site")
    data["links"] = links
    data["name"] = (org.get("legalName") or org.get("name")) if org else site_name
    data["description"] = " ".join(
        str(x) for x in (desc, org.get("description") if org else None, text[:1500]) if x
    )
    data["india_hint"] = bool(
        final_domain.endswith(".in")
        or str(data.get("country", "")).lower() in ("in", "india")
        or INDIAN_HINT.search(" ".join(str(v) for v in (data.get("country"), desc) if v))
    )

    # Thin homepage (common for JS-rendered sites): try /about once.
    if not org and not desc and await robots_allows(urljoin(page.url, "/about")):
        try:
            about = await safe_get(urljoin(page.url, "/about"))
            if about.status == 200:
                ap = _Page()
                ap.feed(about.text)
                d = ap.meta.get("description") or ap.meta.get("og:description")
                if d:
                    ctx.find("one_liner", "website", d.strip()[:280], note="/about meta description")
                    data["description"] += " " + d
                data["about_read"] = True
        except (FetchError, httpx.HTTPError):
            pass

    found = [k for k in ("name", "links") if data.get(k)]
    summary = (
        f"Read {final_domain}"
        + (" — structured Organization data found" if org else " — no structured data, used page text")
        + (f"; links to {', '.join(links)}" if links else "")
    )
    return {"summary": summary, "data": data, "found": found}


# --------------------------------------------------------------------------
# RDAP / DNS / email
# --------------------------------------------------------------------------


async def rdap(ctx: Run, args: dict) -> dict:
    domain = args["domain"]
    try:
        res = await api_get(f"https://rdap.org/domain/{domain}")
    except httpx.HTTPError as exc:
        raise ToolError(f"RDAP unreachable: {exc}") from exc
    if res.status_code == 404:
        raise ToolError(f"No RDAP record for {domain} (some country TLDs don't publish one)")
    if res.status_code != 200:
        raise ToolError(f"RDAP answered HTTP {res.status_code}")
    body = res.json()
    reg = next((e.get("eventDate") for e in body.get("events", [])
                if e.get("eventAction") == "registration"), None)
    registrar = None
    for ent in body.get("entities", []):
        if "registrar" in (ent.get("roles") or []):
            for item in (ent.get("vcardArray") or [None, []])[1]:
                if item and item[0] == "fn":
                    registrar = item[3]
    if not reg:
        raise ToolError("RDAP record has no registration date")
    year = int(reg[:4])
    ctx.find("domain_registered", "rdap", f"{reg[:10]}" + (f" · {registrar}" if registrar else ""))
    ctx.find("founded_year", "rdap", year, suggest=False, compare_as="domain_year",
             note=f"Domain registered {reg[:10]}")
    return {"summary": f"{domain} registered {reg[:10]}" + (f" via {registrar}" if registrar else ""),
            "data": {"registered": reg, "registrar": registrar}}


_MX_PROVIDERS = [
    ("google", "Google Workspace"), ("outlook", "Microsoft 365"), ("zoho", "Zoho Mail"),
    ("amazonaws", "Amazon SES / WorkMail"), ("secureserver", "GoDaddy"), ("mimecast", "Mimecast"),
    ("pphosted", "Proofpoint"), ("protonmail", "Proton"), ("titan", "Titan"),
]


async def _mx(domain: str) -> list[str]:
    res = await api_get("https://dns.google/resolve", params={"name": domain, "type": "MX"})
    if res.status_code != 200:
        raise ToolError(f"DNS lookup failed (HTTP {res.status_code})")
    return [a["data"].split()[-1].rstrip(".").lower() for a in res.json().get("Answer", []) if a.get("type") == 15]


def _provider(mx: list[str]) -> str | None:
    for host in mx:
        for needle, name in _MX_PROVIDERS:
            if needle in host:
                return name
    return mx[0] if mx else None


async def dns(ctx: Run, args: dict) -> dict:
    domain = args["domain"]
    try:
        mx = await _mx(domain)
    except httpx.HTTPError as exc:
        raise ToolError(f"DNS unreachable: {exc}") from exc
    provider = _provider(mx)
    ctx.find("mail_provider", "dns", provider or "No mail servers")
    return {"summary": f"{domain}: " + (f"mail via {provider}" if mx else "no MX records"),
            "data": {"mx": mx, "provider": provider}}


async def email(ctx: Run, args: dict) -> dict:
    addr = args["email"].strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr):
        ctx.find("email", "email", None, force="disagree", blocking=True, kind="local",
                 note="Not a valid email address")
        return {"summary": "Email address is malformed", "data": {}}
    domain = addr.split("@", 1)[1]
    site = args.get("site_domain")
    if domain in checks.FREE_MAIL:
        ctx.find("email", "email", addr, force="neutral",
                 note=f"{domain} is a personal mailbox — it can't tie you to the company")
        return {"summary": f"{domain} is a free mail provider", "data": {"free": True}}
    try:
        mx = await _mx(domain)
    except httpx.HTTPError as exc:
        raise ToolError(f"DNS unreachable: {exc}") from exc
    same = bool(site) and checks.registrable_domain(domain) == site
    if not mx:
        ctx.find("email", "email", addr, force="disagree", note=f"{domain} has no mail servers")
    elif same:
        ctx.find("email", "email", addr, force="agree",
                 note=f"On the company domain and {domain} accepts mail. Ownership is confirmed by code.")
    else:
        ctx.find("email", "email", addr, force="neutral",
                 note=f"{domain} accepts mail but isn't {site or 'the company domain'}")
    return {"summary": f"{domain}: {'matches company domain' if same else 'different domain'}"
                       f"{'' if mx else ', no MX'}",
            "data": {"domain": domain, "matches_site": same, "mx": mx}}


# --------------------------------------------------------------------------
# corpus & sector model (our own data)
# --------------------------------------------------------------------------

_SOURCE_LABEL = {"seed_yc": "YC directory", "seed_india_funding": "Indian funding records",
                 "registration": "an earlier VentureIQ registration"}


def _corpus_lookup(domain: str | None, name: str | None) -> dict | None:
    db = SessionLocal()
    try:
        row = None
        how = ""
        if domain:
            cands = db.query(Startup).filter(Startup.website.ilike(f"%{domain}%")).limit(20).all()
            cands = [c for c in cands if c.website and checks.registrable_domain(c.website) == domain]
            if cands:
                row, how = cands[0], f"domain {domain}"
        if row is None and name:
            key = name.strip().lower()
            row = db.query(Startup).filter(func.lower(Startup.legal_name) == key).first()
            how = f"name “{name}”"
        if row is None:
            return None
        rounds = db.query(FundingRound).filter(FundingRound.startup_id == row.startup_id).all()
        fin = row.latest_financials
        investors = sorted({i for r in rounds for i in (r.investor_names or [])})
        return {
            "startup_id": row.startup_id, "matched_by": how, "source": row.source,
            "name": row.legal_name, "sector": row.sector, "sub_vertical": row.sub_vertical,
            "city": row.hq_city, "founded_year": row.founded_date.year if row.founded_date else None,
            "team_size": row.employee_count, "status": row.status, "website": row.website,
            "one_liner": row.one_liner, "long_description": row.long_description,
            "rounds": len(rounds),
            "funding_usd": sum(r.amount_usd or 0 for r in rounds) or (fin.total_funding_usd if fin and rounds else None),
            "last_round": max(rounds, key=lambda r: r.announced_date or r.round_id).round_stage if rounds else None,
            "investors": investors[:8],
        }
    finally:
        db.close()


async def corpus(ctx: Run, args: dict) -> dict:
    hit = await asyncio.to_thread(_corpus_lookup, args.get("domain"), args.get("name"))
    if not hit:
        return {"summary": "No earlier record — you'd be new to the corpus", "data": {"hit": None}}
    src = _SOURCE_LABEL.get(hit["source"], hit["source"])
    if hit["source"] == "registration":
        # Another founder's registration is a claim, not independent evidence.
        return {"summary": f"Already registered on VentureIQ as “{hit['name']}” (matched by {hit['matched_by']})",
                "data": {"hit": hit}}
    ctx.find("legal_name", "corpus", hit["name"], note=src)
    ctx.find("sector", "corpus", hit["sector"], note=src)
    if hit["sub_vertical"]:
        ctx.find("sub_vertical", "corpus", hit["sub_vertical"], note=src)
    if hit["city"]:
        ctx.find("hq_city", "corpus", hit["city"], note=src)
    if hit["founded_year"]:
        note = "YC batch year — the company may predate it" if hit["source"] == "seed_yc" else src
        ctx.find("founded_year", "corpus", hit["founded_year"], note=note)
    if hit["team_size"]:
        ctx.find("employee_count", "corpus", int(hit["team_size"]), note=f"{src} (may be dated)")
    if hit["one_liner"]:
        ctx.find("one_liner", "corpus", hit["one_liner"], note=src)
    if hit["long_description"]:
        ctx.find("long_description", "corpus", hit["long_description"][:2000], note=src)
    if hit["website"]:
        ctx.find("website", "corpus", hit["website"], note=src)
    if hit["funding_usd"]:
        ctx.find("total_funding_usd", "corpus", round(hit["funding_usd"]),
                 note=f"{hit['rounds']} disclosed round(s)"
                      + (f"; investors include {', '.join(hit['investors'][:3])}" if hit["investors"] else ""))
    return {
        "summary": f"Found in {src} by {hit['matched_by']}"
                   + (f" — {hit['rounds']} funding round(s)" if hit["rounds"] else ""),
        "data": {"hit": hit},
    }


def _vote_sector(text: str, exclude: str | None, domain: str | None) -> dict | None:
    from sklearn.metrics.pairwise import cosine_similarity

    from app.ml import rag

    db = SessionLocal()
    try:
        if not rag.INDEX.built:
            rag.INDEX.build(db)
        if not rag.INDEX.built or rag.INDEX.vectorizer is None:
            return None
        sims = cosine_similarity(rag.INDEX.vectorizer.transform([text]), rag.INDEX.matrix)[0]
        # The company's own corpus record would vote for itself; leave it out.
        skip = set()
        if exclude or domain:
            conds = []
            if exclude:
                conds.append(func.lower(Startup.legal_name) == exclude.strip().lower())
            if domain:
                conds.append(Startup.website.ilike(f"%{domain}%"))
            skip = {r[0] for r in db.query(Startup.startup_id).filter(or_(*conds)).all()}
        order = [i for i in sims.argsort()[::-1][:40] if rag.INDEX.ids[i] not in skip]
        top = order[:15]
        votes: Counter[str] = Counter()
        for i in top:
            if sims[i] <= 0:
                continue
            votes[rag.INDEX.meta[rag.INDEX.ids[i]]["sector"]] += float(sims[i])
        if not votes:
            return None
        sector, weight = votes.most_common(1)[0]
        return {
            "sector": sector,
            "confidence": round(weight / sum(votes.values()), 2),
            "neighbours": [rag.INDEX.meta[rag.INDEX.ids[i]]["legal_name"] for i in top[:5]],
        }
    finally:
        db.close()


async def sector_model(ctx: Run, args: dict) -> dict:
    res = await asyncio.to_thread(_vote_sector, args["text"], args.get("exclude"), args.get("domain"))
    if not res:
        raise ToolError("Not enough text to classify")
    ctx.find("sector", "sector_model", res["sector"],
             note=f"{res['confidence']:.0%} of neighbour weight; nearest: {', '.join(res['neighbours'][:3])}")
    return {"summary": f"Looks like {res['sector']} ({res['confidence']:.0%} vote)", "data": res}


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------


def _rate_limited(res: httpx.Response) -> bool:
    return res.status_code in (403, 429) and res.headers.get("x-ratelimit-remaining") == "0"


async def github_org(ctx: Run, args: dict) -> dict:
    site = args.get("site_domain")
    login = args.get("login")
    via = "linked from your site"
    if not login:
        res = await api_get("https://api.github.com/search/users",
                            params={"q": f"{args['name']} type:org", "per_page": 5}, github=True)
        if _rate_limited(res):
            raise ToolError("GitHub search rate limit reached — try again in a minute")
        cands = [i["login"] for i in res.json().get("items", [])] if res.status_code == 200 else []
        for cand in cands[:3]:
            r = await api_get(f"https://api.github.com/orgs/{cand}", github=True)
            if r.status_code == 200 and site and checks.registrable_domain(r.json().get("blog") or "") == site:
                login, via = cand, "found by search; its website field is your domain"
                break
        if not login:
            return {"summary": f"No GitHub org lists {site or 'your domain'} as its website "
                               f"({len(cands)} name matches checked)", "data": {"candidates": cands}}

    r = await api_get(f"https://api.github.com/orgs/{login}", github=True)
    if _rate_limited(r):
        raise ToolError("GitHub rate limit reached")
    if r.status_code == 404:
        return {"summary": f"github.com/{login} isn't an organisation", "data": {}}
    r.raise_for_status()
    org = r.json()
    repos_res = await api_get(f"https://api.github.com/orgs/{login}/repos",
                              params={"per_page": 100, "sort": "pushed"}, github=True)
    repos = repos_res.json() if repos_res.status_code == 200 else []
    repos = repos if isinstance(repos, list) else []
    stars = sum(x.get("stargazers_count", 0) for x in repos)
    langs = Counter(x.get("language") for x in repos if x.get("language"))
    last_push = max((x.get("pushed_at") or "" for x in repos), default="")[:10]

    blog_domain = checks.registrable_domain(org.get("blog") or "")
    tied = bool(site) and blog_domain == site
    ctx.find("github_org", "github_org", org["login"],
             note=("Org website is your domain" if tied else f"Org website: {org.get('blog') or 'not set'}")
             + f" · {org.get('public_repos', 0)} public repos, {stars} stars",
             force="agree" if tied else None)
    if org.get("location"):
        ctx.find("hq_city", "github_org", org["location"].split(",")[0].strip(), note="GitHub org location")
    if org.get("created_at"):
        ctx.find("founded_year", "github_org", int(org["created_at"][:4]), suggest=False,
                 compare_as="domain_year", note=f"GitHub org created {org['created_at'][:10]}")
    return {
        "summary": f"github.com/{login} — {org.get('public_repos', 0)} repos, {stars} stars"
                   + (f", last push {last_push}" if last_push else "") + f" ({via})",
        "data": {"login": login, "tied_to_domain": tied, "repos": org.get("public_repos"),
                 "stars": stars, "languages": [k for k, _ in langs.most_common(5)],
                 "last_push": last_push, "created_at": org.get("created_at")},
    }


async def github_user(handle: str, founder_name: str, company: str | None) -> dict:
    """Standalone founder check, run when a founder adds a handle during review."""
    res = await api_get(f"https://api.github.com/users/{handle}", github=True)
    if res.status_code == 404:
        return {"status": "conflict", "note": f"github.com/{handle} doesn't exist"}
    if _rate_limited(res):
        return {"status": "claimed", "note": "GitHub rate limit reached — not checked"}
    if res.status_code != 200:
        return {"status": "claimed", "note": f"GitHub answered HTTP {res.status_code}"}
    u = res.json()
    name_ok = checks.compare("name", founder_name, u.get("name") or "") == "agree"
    comp_ok = bool(company) and checks.compare("name", company, (u.get("company") or "").lstrip("@")) == "agree"
    bits = [f"{u.get('public_repos', 0)} repos, {u.get('followers', 0)} followers"]
    if u.get("name"):
        bits.append(f"profile name “{u['name']}”")
    if u.get("company"):
        bits.append(f"company “{u['company']}”")
    status = "verified" if name_ok else ("claimed" if not u.get("name") else "conflict")
    note = ("Profile name matches" if name_ok else "Profile name differs" if u.get("name") else "Profile has no name set")
    if comp_ok:
        note += " · lists this company"
    return {"status": status, "note": f"{note} — {'; '.join(bits)}",
            "data": {k: u.get(k) for k in ("login", "name", "company", "public_repos", "followers", "created_at")}}


async def linkedin_user(url_or_handle: str, founder_name: str, company: str | None) -> dict:
    """Founder LinkedIn check, run when a founder adds a profile link."""
    from app.enrichment import linkedin as li

    handle = li.handle_from(url_or_handle)
    if not handle:
        return {"status": "claimed", "note": "That doesn't look like a personal LinkedIn profile URL"}
    if not li.enabled():
        return {"status": "claimed", "note": "LinkedIn lookups are off (no VIQ_RAPIDAPI_KEY)"}
    try:
        raw = await li.fetch_profile(handle)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hint = {401: "key rejected", 403: "not subscribed to this API", 404: "no such profile",
                429: "rate limit reached"}.get(code, f"HTTP {code}")
        return {"status": "conflict" if code == 404 else "claimed", "note": f"LinkedIn lookup failed — {hint}"}
    except li.QuotaExceeded as exc:
        return {"status": "claimed", "note": f"LinkedIn lookup skipped — {exc}"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "claimed", "note": f"LinkedIn unreachable: {type(exc).__name__}"}

    profile = li.parse_profile(raw)
    if not profile.get("profile_complete"):
        return {"status": "claimed", "note": "Profile fetched but it carries no usable detail",
                "data": profile}
    m = li.matches(profile, founder_name, company)
    status = "verified" if m["name_matches"] and m["company_matches"] else (
        "claimed" if m["name_matches"] else "conflict")
    note = m["summary"]
    if not m["name_matches"]:
        note = f"Profile name is “{profile.get('name')}”, not “{founder_name}” — {note}"
    elif not m["company_matches"]:
        note = f"{note} — but this company isn't listed on the profile"
    return {"status": status, "note": note, "data": profile}


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------


async def cin_check(ctx: Run, args: dict) -> dict:
    d = checks.decode_cin(args["cin"])
    if not d["valid"]:
        ctx.find("cin", "cin_check", None, force="disagree", blocking=True, note=d["error"])
        return {"summary": f"CIN is malformed: {d['error']}", "data": d}
    ctx.find("cin", "cin_check", d["cin"], force="agree",
             note=", ".join(x for x in (d["company_type"], d["state"]) if x))
    if d["incorporation_year"]:
        ctx.find("founded_year", "cin_check", d["incorporation_year"], note="Incorporation year in the CIN")
    if d["state"]:
        ctx.find("hq_state", "cin_check", d["state"], note="Registered state in the CIN")
    if not d["incorporation_year"]:
        return {"summary": f"Well-formed LLPIN ({d['cin']})", "data": d}
    return {"summary": f"{d['company_type']} company, incorporated {d['incorporation_year']} "
                       f"in {d['state'] or d['state_code']}", "data": d}


async def gstin_check(ctx: Run, args: dict) -> dict:
    d = checks.decode_gstin(args["gstin"])
    if not d["valid"]:
        ctx.find("gstin", "gstin_check", None, force="disagree", blocking=True, note=d["error"])
        return {"summary": f"GSTIN rejected: {d['error']}", "data": d}
    note = f"Check digit valid · {d['state']} · PAN holder: {d['pan_holder']}"
    ctx.find("gstin", "gstin_check", d["gstin"], force="agree", note=note)
    if d["state"]:
        ctx.find("hq_state", "gstin_check", d["state"], note="State code in the GSTIN")
    return {"summary": note, "data": d}


async def city_state(ctx: Run, args: dict) -> dict:
    state = checks.CITY_STATE.get(checks.canon_city(args["city"]))
    if not state:
        return {"summary": f"No state mapping for {args['city']}", "data": {}}
    ctx.find("hq_state", "city_state", state, note=f"{args['city']} is in {state}")
    return {"summary": f"{args['city']} → {state}", "data": {"state": state}}


# --------------------------------------------------------------------------
# MCA company registry (real: open government data)
# --------------------------------------------------------------------------

_GENERIC = re.compile(r"\b(software|technologies|technology|tech|solutions|services|labs|india|"
                      r"ventures|systems|digital|global|innovations|networks)\b", re.I)


def registry_evidence(ctx: Run, rec: dict, how: str) -> None:
    """Report one registry record as evidence. `how` is local (dataset) or live (network)."""
    kind = "dataset" if how == "local" else "network"
    status = rec.get("status") or "unknown status"
    registered = rec.get("registered")
    ctx.find("cin", "mca21", rec["cin"], kind=kind,
             note=f"In the MCA registry · {status} · {rec.get('class') or 'company'}")
    ctx.find("legal_name", "mca21", rec["name"].title(), kind=kind, prefer=True,
             note="Registered name (MCA)")
    if registered:
        ctx.find("founded_year", "mca21", int(registered[:4]), kind=kind, prefer=True,
                 note=f"Incorporated {registered}")
    # Capital as filed with the Registrar. The only funding-shaped figure an
    # Indian company can be checked against without buying a document, so it is
    # reported --- and described as issued capital, never as "raised", because
    # share premium sits outside it.
    for key, field, label in (
        ("paidup_capital", "paid_up_capital", "Paid-up capital"),
        ("authorized_capital", "authorized_capital", "Authorised capital"),
    ):
        value = rec.get(key)
        if value and value > 0:
            ctx.find(field, "mca21", float(value), kind=kind,
                     note=f"{label} as filed with the MCA (INR)")
    if rec.get("state"):
        ctx.find("hq_state", "mca21", rec["state"], kind=kind, note="Registered office state")
    if rec.get("city"):
        ctx.find("hq_city", "mca21", rec["city"], kind=kind,
                 note="Registered office city — may differ from where the team works")
    ctx.facts["registry"] = {k: rec.get(k) for k in (
        "cin", "name", "status", "class", "registered", "state", "city", "industry",
        "paidup_capital", "authorized_capital")}
    if status != "Active":
        ctx.think(f"The registry lists {rec['name'].title()} as “{status}”. That's flagged for review.")
        ctx.find("cin", "mca21", None, kind=kind, force="disagree", suggest=False,
                 note=f"Registry status is “{status}”, not Active")


def _pick_candidate(name: str, cands: list[dict]) -> dict | None:
    """Only auto-pick when the match is unambiguous; otherwise let the founder choose."""
    key = checks.norm_text(name)
    exact = [c for c in cands if checks.norm_text(c["name"]) == key]
    if len(exact) == 1:
        return exact[0]
    loose_key = checks.norm_text(_GENERIC.sub(" ", name))
    loose = [c for c in cands if c.get("status") == "Active"
             and checks.norm_text(_GENERIC.sub(" ", c["name"])) == loose_key]
    return loose[0] if len(loose) == 1 else None


async def mca21(ctx: Run, args: dict) -> dict:
    from app.registry import store as registry

    cin, name = args.get("cin"), args.get("name")
    try:
        if cin:
            rec, how = await registry.lookup_cin(cin)
            if not rec:
                ctx.find("cin", "mca21", None, force="disagree", kind="network",
                         note="This CIN isn't in the MCA registry — check for a typo")
                return {"summary": f"{cin} not found in the MCA registry", "data": {"found": False}}
            registry_evidence(ctx, rec, how)
            return {"summary": f"{rec['name'].title()} · {rec['status']} · incorporated {rec['registered']}"
                               f" ({'local copy' if how == 'local' else 'live data.gov.in lookup'})",
                    "data": {"found": True, "how": how, **{k: rec[k] for k in ("cin", "name", "status")}}}

        cands, how = [], "live"
        if registry.available():
            cands, how = await asyncio.to_thread(registry.search_local, name, 8), "local"
        if not cands:  # no local copy, or a partial one: try exact registered names live
            how = "live"
            for variant in registry.name_variants(name)[:4]:
                cands = await registry.fetch_live({"CompanyName": variant}, limit=5)
                if cands:
                    break
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise ToolError("data.gov.in rate limit reached — add VIQ_DATA_GOV_IN_KEY for a private quota") from exc
        raise ToolError(f"Registry lookup failed (HTTP {exc.response.status_code})") from exc

    rec = _pick_candidate(name, cands)
    if rec:
        registry_evidence(ctx, rec, how)
        return {"summary": f"Matched “{name}” to {rec['name'].title()} ({rec['cin']}, {rec['status']})",
                "data": {"found": True, "how": how, "cin": rec["cin"], "name": rec["name"], "status": rec["status"]}}
    if cands:
        ctx.facts["registry_candidates"] = [{**c, "how": how} for c in cands[:6]]
        return {"summary": f"{len(cands)} registered companies could be “{name}” — pick yours to confirm",
                "data": {"found": False, "candidates": len(cands)}}
    note = "" if registry.stats().get("complete") else " (fuzzy search needs the full registry import)"
    return {"summary": f"No registered company found for “{name}”{note}", "data": {"found": False}}


# --------------------------------------------------------------------------
# mocks (consent- or fee-gated in reality)
# --------------------------------------------------------------------------


async def gstn(ctx: Run, args: dict) -> dict:
    from app.enrichment import gst

    gstin = args["gstin"]
    if gst.enabled():
        try:
            profile = gst.parse(await gst.fetch(gstin))
        except (httpx.HTTPError, gst.QuotaExceeded, RuntimeError) as exc:
            raise ToolError(f"GST lookup failed: {type(exc).__name__}") from exc
        if not profile.get("legal_name"):
            ctx.find("gstin", "gstn", None, kind="network", force="disagree",
                     note="This GSTIN isn't in the GST taxpayer register")
            return {"summary": f"{gstin} not found in the GST register", "data": {"found": False}}
        note = f"{profile['status'] or 'status unknown'} · {profile.get('taxpayer_type') or 'taxpayer'}"
        ctx.find("gstin", "gstn", gstin, kind="network",
                 force="agree" if profile["active"] else "disagree", note=note)
        ctx.find("legal_name", "gstn", profile["legal_name"].title(), kind="network",
                 note="Legal name on the GST register")
        if profile.get("state"):
            ctx.find("hq_state", "gstn", profile["state"].split(",")[0].strip(), kind="network",
                     note="State jurisdiction on the GST register")
        if not profile["active"]:
            ctx.think(f"The GST register lists this GSTIN as “{profile['status']}”, not Active.")
        ctx.facts["gst_profile"] = profile
        if profile.get("turnover_min_inr") or profile.get("turnover_max_inr"):
            ctx.facts["gst_turnover_band_inr"] = [profile.get("turnover_min_inr"),
                                                  profile.get("turnover_max_inr")]
        elif profile.get("turnover_withheld"):
            ctx.think("The GST register has a turnover band, but this API tier withholds it; "
                      "revenue reconciliation stays simulated.")
        # Exact turnover is private; the consented pull is still simulated.
        rng = _seed_for("onboard-gstn", gstin)
        return {"summary": f"{profile['legal_name'].title()} — {profile['status']}"
                           f"{', registered ' + profile['registration_date'] if profile['registration_date'] else ''}",
                "data": {"found": True, **{k: v for k, v in profile.items() if not k.startswith("_")},
                         "turnover_factor": rng.choice([0.94, 0.97, 1.0, 1.02, 0.96, 0.99, 0.58])}}

    await asyncio.sleep(0.5)
    rng = _seed_for("onboard-gstn", args["gstin"])
    returns = rng.randint(9, 12)
    ctx.find("gstin", "gstn", args["gstin"], note=f"Active, {returns}/12 returns filed (mocked)")
    return {"summary": f"GSTIN active, {returns}/12 monthly returns filed (mocked)",
            "data": {"status": "Active", "returns_filed_12m": returns,
                     "turnover_factor": rng.choice([0.94, 0.97, 1.0, 1.02, 0.96, 0.99, 0.58])}}


async def linkedin_company(ctx: Run, args: dict) -> dict:
    await asyncio.sleep(0.4)
    rng = _seed_for("onboard-linkedin", args["url"])
    band = rng.choice([(2, 10), (11, 50), (51, 200), (201, 500)])
    ctx.find("employee_count", "linkedin_company", band[1], suggest=False,
             note=f"Headcount band {band[0]}–{band[1]} (mocked)")
    return {"summary": f"Company page: {band[0]}–{band[1]} employees (mocked)", "data": {"band": band}}


RUNNERS = {
    "website": website, "rdap": rdap, "dns": dns, "email": email, "corpus": corpus,
    "sector_model": sector_model, "github_org": github_org, "cin_check": cin_check,
    "gstin_check": gstin_check, "city_state": city_state, "mca21": mca21, "gstn": gstn,
    "linkedin_company": linkedin_company,
}
