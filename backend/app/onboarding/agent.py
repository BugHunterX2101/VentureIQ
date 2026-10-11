"""Agentic startup onboarding.

The founder gives us three things (website, work email, stage). The agent then
decides what to look up, in what order, and *why*, reacting to each result:

  website read  → name, description and profile links become known
                → a linked GitHub org gets confirmed; otherwise search by name
                → a description gets classified into a sector
                → Indian signals (CIN, GSTIN, .in, an Indian city) unlock MCA21
  site unreadable → fall back to the corpus and registry by name
  GSTIN valid   → GST filings, but only with the founder's consent

Every decision is streamed as an event, so the founder watches the research
happen and can see which findings came from live sources and which from mocks.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any

import httpx

from app.core.database import SessionLocal
from app.models import OnboardingSession
from app.onboarding import checks
from app.onboarding.ledger import reconcile
from app.onboarding.tools import RUNNERS, TOOLS, ToolError

TOOL_TIMEOUT_S = 20

SOURCE_TOOL = {"website_jsonld": "website"}
SOURCE_LABEL = {"website_jsonld": "Company website (structured data)"}

INPUT_KEYS = ("website", "email", "stage", "legal_name", "cin", "gstin")


class Run:
    """In-memory state for one onboarding session, mirrored to the database."""

    def __init__(self, row: OnboardingSession) -> None:
        self.session_id = row.session_id
        self.status = row.status
        self.inputs: dict[str, Any] = dict(row.inputs or {})
        self.evidence: dict[str, list[dict]] = dict(row.evidence or {})
        self.overrides: dict[str, Any] = dict(row.overrides or {})
        self.tool_results: dict[str, Any] = dict(row.tool_results or {})
        self.events: list[dict] = list(row.events or [])
        self.startup_id = row.startup_id
        self.user_id = row.user_id
        self.facts: dict[str, Any] = dict(self.tool_results.get("_facts", {}))
        self._tick = asyncio.Event()
        self._t0 = time.monotonic()
        self._current_tool: str | None = None
        # Bumped whenever the ledger changes; the stream sends a fresh snapshot.
        # Snapshots are transient, so they aren't stored in the event log.
        self.state_version = 0

    # ---------------------------------------------------------------- events
    def emit(self, event: dict) -> None:
        event = {"seq": len(self.events), "t": round((time.monotonic() - self._t0) * 1000), **event}
        self.events.append(event)
        tick, self._tick = self._tick, asyncio.Event()
        tick.set()

    async def wait(self) -> None:
        await self._tick.wait()

    def touch(self) -> None:
        self.state_version += 1
        tick, self._tick = self._tick, asyncio.Event()
        tick.set()

    def think(self, text: str) -> None:
        self.emit({"type": "thought", "text": text})

    # -------------------------------------------------------------- evidence
    def find(
        self,
        field: str,
        source: str,
        value: Any,
        *,
        note: str = "",
        kind: str | None = None,
        suggest: bool = True,
        force: str | None = None,
        blocking: bool = False,
        compare_as: str | None = None,
        prefer: bool = False,
    ) -> None:
        tool = SOURCE_TOOL.get(source, source)
        spec = TOOLS.get(tool, {})
        ev = {
            "source": source,
            "tool": tool,
            "label": SOURCE_LABEL.get(source, spec.get("label", source)),
            "kind": kind or spec.get("kind", "network"),
            "value": value,
            "note": note,
            "suggest": suggest,
        }
        if force:
            ev["force"] = force
        if blocking:
            ev["blocking"] = True
        if compare_as:
            ev["compare_as"] = compare_as
        if prefer:
            ev["prefer"] = True  # authoritative for this field (e.g. registered name)
        bucket = self.evidence.setdefault(field, [])
        bucket[:] = [e for e in bucket if not (e["source"] == source and e.get("value") == value)]
        bucket.append(ev)
        self.emit({"type": "finding", "tool": self._current_tool, "field": field, **ev})

    # ---------------------------------------------------------------- ledger
    def claims(self) -> dict[str, Any]:
        return {k: self.inputs.get(k) for k in INPUT_KEYS if self.inputs.get(k)}

    def ledger(self) -> dict[str, Any]:
        return reconcile(self.claims(), self.evidence, self.overrides)

    def value(self, key: str) -> Any:
        row = next((f for f in self.ledger()["fields"] if f["key"] == key), None)
        return row["value"] if row else None

    def snapshot(self) -> dict[str, Any]:
        ledger = self.ledger()
        founders = self.facts.get("founders", [])
        if not any(f.get("name") for f in founders):
            ledger["blocking"].append("founders")
        return {
            "session_id": self.session_id,
            "status": self.status,
            "inputs": self.inputs,
            "ledger": ledger,
            "founders": founders,
            "facts": {k: v for k, v in self.facts.items() if k != "founders"},
            "gst_consent": bool(self.inputs.get("gst_consent")),
            "startup_id": self.startup_id,
        }

    # ----------------------------------------------------------- persistence
    def save(self) -> None:
        db = SessionLocal()
        try:
            row = db.get(OnboardingSession, self.session_id)
            if row is None:
                return
            row.status = self.status
            row.inputs = self.inputs
            row.evidence = self.evidence
            row.overrides = self.overrides
            row.tool_results = {**self.tool_results, "_facts": self.facts}
            row.events = self.events
            row.startup_id = self.startup_id
            row.user_id = self.user_id
            db.commit()
        finally:
            db.close()


RUNS: dict[str, Run] = {}


def create_session(inputs: dict[str, Any], user_id: str | None = None) -> Run:
    db = SessionLocal()
    try:
        row = OnboardingSession(inputs=inputs, evidence={}, overrides={}, tool_results={},
                                events=[], user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
        run = Run(row)
    finally:
        db.close()
    founder_name = (inputs.get("founder_name") or "").strip()
    if founder_name:
        run.facts["founders"] = [{
            "name": founder_name, "role": inputs.get("founder_role") or "Founder",
            "github": None, "linkedin": None, "source": "founder", "check": None,
        }]
    RUNS[run.session_id] = run
    return run


def get_run(session_id: str) -> Run | None:
    if session_id in RUNS:
        return RUNS[session_id]
    db = SessionLocal()
    try:
        row = db.get(OnboardingSession, session_id)
        if row is None:
            return None
        run = Run(row)
        if run.status == "running":  # the server restarted mid-run
            run.status = "ready"
            run.emit({"type": "thought", "text": "Research was interrupted; showing what was found."})
        RUNS[session_id] = run
        return run
    finally:
        db.close()


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


async def execute(run: Run) -> None:
    inp = run.inputs
    site = checks.normalise_website(inp.get("website", ""))
    domain = checks.registrable_domain(site) if site else None
    run.facts.update({"domain": domain, "india": bool(inp.get("cin") or inp.get("gstin"))})

    queue: list[tuple[str, str, dict, str]] = []
    planned: set[str] = set()

    def plan(tool: str, reason: str, key: str | None = None, **args: Any) -> None:
        key = key or tool
        if key in planned:
            return
        planned.add(key)
        queue.append((key, tool, args, reason))
        t = TOOLS[tool]
        run.emit({"type": "plan", "id": key, "tool": tool, "label": t["label"],
                  "kind": t["kind"], "reason": reason})

    run.emit({"type": "start", "domain": domain})
    if site:
        run.think(f"Starting from {domain}. Everything else should be findable from there.")
        plan("website", f"You gave us {domain} — the cheapest way to learn who you are.", url=site)
        plan("rdap", "Domain age is an independent check on the founding year.", domain=domain)
        plan("dns", "A domain that receives mail is a real, operating company domain.", domain=domain)
    else:
        run.think("No website given, so the agent will lean on the company name, registry and corpus.")
    if inp.get("email"):
        plan("email", "Your email should live on the company's domain.",
             email=inp["email"], site_domain=domain)
    plan("corpus", "Check whether public records already mention you.",
         domain=domain, name=inp.get("legal_name"))
    if inp.get("cin"):
        plan("cin_check", "A CIN encodes state, year and company type — decode it before querying.", cin=inp["cin"])
    if inp.get("gstin"):
        plan("gstin_check", "Validate the GSTIN check digit before anything else relies on it.", gstin=inp["gstin"])

    while queue:
        key, tool, args, _reason = queue.pop(0)
        run.emit({"type": "step", "id": key, "tool": tool, "status": "running"})
        run._current_tool = key
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(RUNNERS[tool](run, args), TOOL_TIMEOUT_S)
            ok, summary, data, error = True, result.get("summary", ""), result.get("data", {}), None
        except ToolError as exc:
            ok, summary, data, error = False, str(exc), {}, str(exc)
        except TimeoutError:
            ok, summary, data, error = False, f"Timed out after {TOOL_TIMEOUT_S}s", {}, "timeout"
        except (httpx.HTTPError, ValueError) as exc:
            ok, summary, data, error = False, f"{type(exc).__name__}: {exc}", {}, str(exc)
        run._current_tool = None
        ms = round((time.monotonic() - t0) * 1000)
        run.tool_results[key] = {"tool": tool, "ok": ok, "summary": summary, "data": data,
                                 "error": error, "ms": ms, "kind": TOOLS[tool]["kind"]}
        run.emit({"type": "step_done", "id": key, "tool": tool, "ok": ok, "summary": summary, "ms": ms})
        _react(run, key, tool, ok, data, plan, domain)
        run.touch()

    city = run.value("hq_city")
    if city and not run.evidence.get("hq_state"):
        plan("city_state", "Derive the state from the city.", city=city)
        key, tool, args, _ = queue.pop(0)
        run.emit({"type": "step", "id": key, "tool": tool, "status": "running"})
        res = await RUNNERS[tool](run, args)
        run.tool_results[key] = {"tool": tool, "ok": True, "summary": res["summary"], "data": res["data"],
                                 "error": None, "ms": 0, "kind": "local"}
        run.emit({"type": "step_done", "id": key, "tool": tool, "ok": True, "summary": res["summary"], "ms": 0})

    ledger = run.ledger()
    c = ledger["counts"]
    run.think(
        f"Done. {c.get('verified', 0)} verified, {c.get('fetched', 0)} filled in for you to confirm, "
        f"{c.get('conflict', 0)} conflict(s), {c.get('missing', 0)} still needed from you."
    )
    run.status = "ready"
    run.emit({"type": "done"})
    run.save()


def _react(run: Run, key: str, tool: str, ok: bool, data: dict, plan: Any, domain: str | None) -> None:
    inp = run.inputs
    name = inp.get("legal_name")

    if tool == "website":
        if not ok:
            run.find("website", "website", None, force="disagree", suggest=False,
                     note=run.tool_results[key]["summary"])
            run.think("Couldn't read the site, so falling back to the registry and corpus by name."
                      + ("" if name else " We'll need the company name from you."))
            if name and not run.facts.get("corpus_hit"):
                plan("corpus", f"Search the corpus for “{name}”.", key="corpus_name", name=name)
            _maybe_registry(run, plan, name)
            return
        name = data.get("name") or name
        run.facts["name"] = name
        if data.get("founders"):
            existing = run.facts.setdefault("founders", [])
            known = {checks.norm_text(f["name"]) for f in existing}
            for n in data["founders"]:
                if checks.norm_text(n) not in known:
                    existing.append({"name": n, "role": "Founder", "github": None, "linkedin": None,
                                     "source": "website", "check": None})
            run.think(f"Your site names {len(data['founders'])} founder(s); added them for you to confirm.")
        links = data.get("links", {})
        if links.get("github"):
            plan("github_org", f"Your site links to github.com/{links['github']} — confirming it's yours.",
                 login=links["github"], site_domain=domain)
        elif name:
            plan("github_org", f"No GitHub link on your site. Searching for “{name}”, and only accepting "
                               f"an org that lists {domain} as its website.", name=name, site_domain=domain)
        if links.get("linkedin"):
            plan("linkedin_company", "Your site links a LinkedIn page; headcount would come from there.",
                 url=links["linkedin"])
        if (data.get("description") or "").strip():
            plan("sector_model", "Classify the sector from how you describe yourself.",
                 text=f"{name or ''} {data['description']}"[:4000], exclude=name, domain=domain)
        if data.get("india_hint"):
            run.facts["india"] = True
        if name and not run.facts.get("corpus_hit") and "corpus" in run.tool_results:
            plan("corpus", f"No record under {domain}; trying the name “{name}”.", key="corpus_name", name=name)
        _maybe_registry(run, plan, name)

    elif tool == "corpus" and ok and data.get("hit"):
        hit = data["hit"]
        run.facts["corpus_hit"] = {k: hit[k] for k in ("startup_id", "source", "name", "rounds")}
        if hit["source"] == "registration":
            run.facts["duplicate_of"] = hit["startup_id"]
            run.think("This company is already registered on VentureIQ. Submitting again will be flagged "
                      "for review as a possible duplicate.")
        if hit.get("city") and checks.CITY_STATE.get(checks.canon_city(hit["city"])):
            run.facts["india"] = True
            _maybe_registry(run, plan, run.facts.get("name") or hit["name"])
        if "sector_model" not in run.tool_results and hit.get("long_description") and \
                not any(q for q in ("website",) if run.tool_results.get(q, {}).get("ok")):
            plan("sector_model", "No readable site — classifying from the public record's description.",
                 text=f"{hit['name']} {hit['long_description']}"[:4000], exclude=hit["name"], domain=domain)

    elif tool == "cin_check":
        if ok and data.get("valid"):
            run.facts["india"] = True
            _maybe_registry(run, plan, run.facts.get("name") or name)
        else:
            run.think("The CIN fails its format check, so the registry lookup waits until it's fixed.")

    elif tool == "gstin_check":
        if ok and data.get("valid"):
            run.facts["india"] = True
            if inp.get("gst_consent"):
                plan("gstn", "GSTIN is valid and you consented — pulling filing status.", gstin=data["gstin"])
            else:
                run.think("GSTIN is valid. GST returns need your consent, so revenue won't be "
                          "cross-checked unless you give it.")
            _maybe_registry(run, plan, run.facts.get("name") or name)

    elif tool == "gstn" and ok:
        run.facts["gst_turnover_factor"] = data.get("turnover_factor")


def _maybe_registry(run: Run, plan: Any, name: str | None) -> None:
    """MCA21 only makes sense for Indian entities — decide, and say why."""
    if "mca21" in run.tool_results:
        return
    # "Not Indian" is a provisional answer, not a final one. The website is
    # usually read before the corpus answers, and a .tech or .ai domain rarely
    # says "India" on the homepage --- BharatX, registered in Bengaluru, was
    # skipped on exactly that basis. So a later source that does establish an
    # Indian entity reopens the decision.
    if run.facts.get("registry_decided") and not run.facts.get("india"):
        return
    cin = run.inputs.get("cin")
    cin_ok = cin and checks.decode_cin(cin)["valid"]
    if cin and not cin_ok:
        return
    if not run.facts.get("india"):
        if "website" in run.tool_results:  # decide once we've seen the site
            run.facts["registry_decided"] = True
            run.think("Nothing so far suggests an Indian entity, so the MCA21 and GST registries "
                      "are skipped for now.")
        return
    if run.facts.get("registry_decided") and not run.facts.get("registry_reopened"):
        run.facts["registry_reopened"] = True
        run.think("A later source places this company in India after all — checking the MCA registry.")
    if not (cin_ok or name):
        return
    run.facts["registry_decided"] = True
    plan("mca21", "Indian entity: looking it up in the MCA company registry"
         + (" by your CIN." if cin_ok else f" by name, “{name}” (no CIN given)."),
         cin=cin if cin_ok else None, name=name)


# --------------------------------------------------------------------------
# edits, founder checks, submit
# --------------------------------------------------------------------------


def clear_source(run: Run, source: str) -> None:
    for field in run.evidence:
        run.evidence[field] = [e for e in run.evidence[field] if e["source"] != source]


async def apply_edit(run: Run, key: str, value: Any = None, resolution: str | None = None) -> None:
    entry = dict(run.overrides.get(key) or {})
    if resolution == "accept":
        row = next((f for f in run.ledger()["fields"] if f["key"] == key), None)
        if row and row.get("suggestion"):
            entry = {"value": row["suggestion"]["value"], "resolution": "accept"}
    elif resolution == "keep":
        row = next((f for f in run.ledger()["fields"] if f["key"] == key), None)
        entry = {"value": row["value"] if row else value, "resolution": "keep"}
    else:
        entry = {"value": value}
    run.overrides[key] = entry

    # Identifier edits are cheap to re-check offline, so re-check them now.
    if key in ("cin", "gstin") and resolution is None:
        source = f"{key}_check"
        # Registry pulls were for the old number; they no longer describe this one.
        run.evidence[key] = [e for e in run.evidence.get(key, []) if e["source"] != source]
        clear_source(run, "gstn" if key == "gstin" else "mca21")
        if key == "cin":
            run.facts.pop("registry", None)
        if key == "gstin" and run.facts.pop("gst_turnover_factor", None) is not None:
            run.evidence.pop("revenue", None)
            run.think("GSTIN changed, so the earlier GST filing pull no longer applies to it.")
        if entry.get("value"):
            decoded = (checks.decode_cin if key == "cin" else checks.decode_gstin)(str(entry["value"]))
            if decoded["valid"]:
                run.find(key, source, decoded[key], force="agree", note="Re-checked after your edit")
                if key == "cin":
                    await _relookup_cin(run, decoded["cin"])
            else:
                run.find(key, source, None, force="disagree", blocking=True, note=decoded["error"])

    # Revenue meets GST: only with consent and a filing pull on record.
    if key == "revenue" and run.facts.get("gst_turnover_factor") and entry.get("value"):
        try:
            claimed = float(entry["value"])
        except (TypeError, ValueError):
            claimed = 0
        if claimed > 0:
            run.evidence["revenue"] = []
            filed = round(claimed * run.facts["gst_turnover_factor"])
            gap = abs(claimed - filed) / claimed
            run.find("revenue", "gstn", filed, suggest=False,
                     force="disagree" if gap > 0.2 else "agree",
                     note=f"GST-reported turnover ${filed:,.0f} — {gap:.0%} gap (mocked filing)")
    run.save()


async def _relookup_cin(run: Run, cin: str) -> None:
    """A founder picked or typed a CIN: confirm it against the registry now."""
    from app.onboarding.tools import registry_evidence
    from app.registry import store as registry

    picked = next((c for c in run.facts.get("registry_candidates", []) if c["cin"] == cin), None)
    try:
        rec, how = (picked, picked["how"]) if picked else await registry.lookup_cin(cin)
    except httpx.HTTPError as exc:
        run.think(f"Couldn't reach the registry to confirm {cin}: {exc}")
        return
    run._current_tool = "mca21"
    if rec:
        registry_evidence(run, rec, how)
        run.facts.pop("registry_candidates", None)
        run.tool_results["mca21"] = {"tool": "mca21", "ok": True, "kind": "network", "ms": 0, "error": None,
                                     "summary": f"Confirmed {rec['name'].title()} ({cin}) after your edit",
                                     "data": {"found": True, "cin": cin, "name": rec["name"], "status": rec["status"]}}
    else:
        run.find("cin", "mca21", None, force="disagree", kind="network",
                 note="This CIN isn't in the MCA registry — check for a typo")
    run._current_tool = None


def set_founders(run: Run, founders: list[dict]) -> None:
    prev = {checks.norm_text(f["name"]): f for f in run.facts.get("founders", [])}
    out = []
    for f in founders:
        old = prev.get(checks.norm_text(f.get("name", "")), {})
        keep_check = old.get("github") == f.get("github")
        out.append({
            "name": f.get("name", "").strip(), "role": f.get("role") or None,
            "github": (f.get("github") or "").strip().lstrip("@") or None,
            "linkedin": f.get("linkedin") or None,
            "source": old.get("source", "founder"),
            "check": old.get("check") if keep_check else None,
        })
    run.facts["founders"] = [f for f in out if f["name"]]
    run.save()


async def check_founder(run: Run, index: int) -> dict:
    """Check one founder against the public profiles they claim."""
    from app.onboarding.tools import github_user, linkedin_user

    founders = run.facts.get("founders", [])
    f = founders[index]
    company = run.value("legal_name")
    checks: list[dict] = []

    if f.get("github"):
        try:
            res = await github_user(f["github"], f["name"], company)
        except httpx.HTTPError as exc:
            res = {"status": "claimed", "note": f"GitHub unreachable: {exc}"}
        checks.append({**res, "label": "GitHub", "kind": "network", "source": "github_user"})

    if f.get("linkedin"):
        res = await linkedin_user(f["linkedin"], f["name"], company)
        checks.append({**res, "label": "LinkedIn", "kind": "network", "source": "linkedin_profile"})

    if not checks:
        checks.append({"status": "claimed", "label": "Profiles",
                       "note": "Add a GitHub handle or LinkedIn URL to check this founder",
                       "kind": "network"})

    f["checks"] = checks
    # Worst status wins for the summary badge.
    order = {"conflict": 0, "claimed": 1, "verified": 2}
    f["check"] = sorted(checks, key=lambda c: order.get(c["status"], 1))[0]
    run.save()
    return f


DOC_FIELD_MAP = {
    "cin": "cin",
    "gstin": "gstin",
    "company_name": "legal_name",
    "incorporation_date": "founded_year",
    "revenue": "revenue",
}


def apply_document(run: Run, filename: str, path: Any, parsed: dict[str, Any]) -> None:
    """A document the founder uploaded becomes evidence, the same as any source.

    A document is the founder's own artefact, so on its own it is corroboration,
    not proof — except where an independent source agrees with it, which is why
    the registry checks travel with it.
    """
    label = parsed["doc_type_label"]
    run._current_tool = "document"
    registry_ok = any(c["check"] == "cin_in_registry" and c["status"] == "verified"
                      for c in parsed["checks"])

    for field in parsed["fields"]:
        key = DOC_FIELD_MAP.get(field["key"])
        if not key:
            continue
        value = field["value"]
        if key == "founded_year":
            value = int(str(value)[:4])
        # The registry confirming the CIN is what lets a document verify anything.
        kind = "dataset" if (registry_ok and key in ("cin", "legal_name", "founded_year")) else "local"
        note = f"Read from {filename} ({label})"
        if field.get("note"):
            note += f" — {field['note']}"
        run.find(key, "document", value, kind=kind, note=note,
                 prefer=registry_ok and key in ("cin", "legal_name"))

    for check in parsed["checks"]:
        if check["status"] == "conflict":
            run.think(f"{label}: {check['detail']}")

    run.facts.setdefault("documents", []).append({
        "filename": filename,
        "doc_type": parsed["doc_type"],
        "doc_type_label": label,
        "pages": parsed["pages"],
        "ocr_confidence": parsed["ocr_confidence"],
        "stored_at": str(path),
        "fields": [f["key"] for f in parsed["fields"]],
        "checks": parsed["checks"],
    })
    run.tool_results[f"document-{len(run.facts['documents'])}"] = {
        "tool": "document", "ok": True, "kind": "network", "ms": 0, "error": None,
        "summary": f"{label}: {len(parsed['fields'])} field(s) read from {filename}"
                   + (" · CIN confirmed in the MCA registry" if registry_ok else ""),
        "data": {"filename": filename, "checks": parsed["checks"]},
    }
    run._current_tool = None
    run.touch()
    run.save()


async def submit(run: Run) -> str:
    """Turn a reconciled session into a Startup, with provenance attached."""
    from app.api.routes.startups import _cohort_stats
    from app.enrichment.agent import enrich_startup
    from app.ml import rag
    from app.ml.scoring import compute_scores
    from app.models import (
        AuditLog, EnrichmentRecord, Founder, FraudSignal, Startup, StartupDocument, StartupFinancials,
    )

    snap = run.snapshot()
    if snap["ledger"]["blocking"]:
        raise ValueError("Resolve these first: " + ", ".join(snap["ledger"]["blocking"]))
    vals = {f["key"]: f["value"] for f in snap["ledger"]["fields"]}
    status = {f["key"]: f["status"] for f in snap["ledger"]["fields"]}

    def num(k: str) -> float | None:
        try:
            return float(vals[k]) if vals.get(k) not in (None, "") else None
        except (TypeError, ValueError):
            return None

    db = SessionLocal()
    try:
        mca = run.tool_results.get("mca21", {})
        s = Startup(
            legal_name=str(vals["legal_name"]).strip(),
            stage=run.inputs["stage"],
            sector=vals["sector"],
            sub_vertical=vals.get("sub_vertical"),
            founded_date=date(int(vals["founded_year"]), 1, 1),
            hq_city=vals.get("hq_city"),
            hq_state=vals.get("hq_state"),
            website=vals.get("website"),
            cin=vals.get("cin") if status.get("cin") in ("claimed", "verified", "fetched") else None,
            gstin=vals.get("gstin") if status.get("gstin") in ("claimed", "verified") else None,
            one_liner=(vals.get("one_liner") or "")[:280] or None,
            long_description=vals.get("long_description"),
            employee_count=int(num("employee_count")) if num("employee_count") else None,
            source="registration",
            verified=bool(mca.get("ok") and mca.get("data", {}).get("found")),
            owner_user_id=run.user_id,
        )
        db.add(s)
        db.flush()

        for f in run.facts.get("founders", []):
            db.add(Founder(startup_id=s.startup_id, name=f["name"], role=f.get("role"),
                           linkedin_url=f.get("linkedin"), github_username=f.get("github")))

        gst_ev = next((e for e in run.evidence.get("revenue", []) if e["source"] == "gstn"), None)
        if run.inputs["stage"] != "idea" or num("revenue"):
            db.add(StartupFinancials(
                startup_id=s.startup_id, as_of_date=date.today(),
                revenue=num("revenue"), burn_rate_monthly=num("burn_rate_monthly"),
                cash_balance=num("cash_balance"), mrr=num("mrr"),
                active_users=int(num("active_users")) if num("active_users") else None,
                total_funding_usd=num("total_funding_usd"),
                gst_reported_revenue=gst_ev["value"] if gst_ev else None,
            ))

        for doc in run.facts.get("documents", []):
            db.add(StartupDocument(
                startup_id=s.startup_id,
                doc_type=doc["doc_type"],
                filename=doc["filename"],
                s3_key=doc.get("stored_at"),
                layoutlm_entities={"fields": doc["fields"], "pages": doc["pages"]},
                extraction_confidence=doc.get("ocr_confidence"),
                deviation_flags=doc["checks"],
            ))

        stored_as = {"rdap": "whois"}
        for key, res in run.tool_results.items():
            if key.startswith("_"):
                continue
            db.add(EnrichmentRecord(
                startup_id=s.startup_id,
                source=stored_as.get(res["tool"], res["tool"]),
                is_mock=res["kind"] == "mock",
                query_params={"onboarding_session": run.session_id, "step": key},
                raw_response={"summary": res["summary"], **(res.get("data") or {})},
                status="success" if res["ok"] else "failed",
                error=res.get("error"),
            ))

        for f in snap["ledger"]["fields"]:
            if f["status"] == "disputed":
                db.add(FraudSignal(
                    startup_id=s.startup_id, detector="rule", anomaly_score=0.5,
                    flagged_fields=[f["key"]], severity="medium",
                    explanation=f"At registration the founder kept “{f['value']}” for {f['label']} "
                                f"although {f['note'] or 'an independent source disagreed'}.",
                ))
        if run.facts.get("duplicate_of"):
            db.add(FraudSignal(
                startup_id=s.startup_id, detector="rule", anomaly_score=0.8,
                flagged_fields=["website"], severity="high",
                explanation="Registered again with a website that already belongs to a VentureIQ profile.",
            ))

        db.add(AuditLog(
            action="startup.registered", entity_type="startup", entity_id=s.startup_id,
            detail={"onboarding_session": run.session_id, "counts": snap["ledger"]["counts"],
                    "statuses": status},
        ))
        db.commit()
        db.refresh(s)

        # Founder-level checks (live GitHub, mocked LinkedIn) run through the
        # same agent the rest of the platform uses; company-level sources are
        # already on record, so its cache skips them.
        await enrich_startup(db, s)
        db.refresh(s)
        compute_scores(db, s, cohort_stats=_cohort_stats(db, s))
        db.commit()
        rag.INDEX.built = False
        startup_id = s.startup_id
    finally:
        db.close()

    run.startup_id = startup_id
    run.status = "submitted"
    run.emit({"type": "submitted", "startup_id": startup_id})
    run.save()
    return startup_id
