"""Field ledger: what we know about each registration field, and how sure we are.

Each field collects *evidence* — a value plus the source that produced it and
whether that source is a live network lookup, a local computation, or a mock.
`reconcile` turns founder claims and evidence into one status per field:

  verified   an independent source (live lookup or public dataset) agrees
  fetched    the agent filled it in; the founder should glance at it
  claimed    the founder's word only; nothing public can check it
  conflict   a live source disagrees — the founder must accept or keep
  disputed   founder kept their value despite a disagreeing source
  missing    required, and nobody has supplied it yet

The rule that keeps this honest: mock and local evidence can *support* a value
but never mark it verified on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.onboarding.checks import compare

SOURCE_RANK = [
    "founder", "website_jsonld", "website", "corpus", "github_org", "rdap", "dns",
    "email", "cin_check", "gstin_check", "sector_model", "city_state",
    "mca21", "gstn", "linkedin_company",
]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    kind: str = "text"  # comparator; see checks.compare
    required: bool = False
    founder_only: bool = False  # no public source can supply it
    readonly: bool = False  # informational, derived by the agent
    hint: str = ""


FIELDS: list[FieldSpec] = [
    # --- what the founder types to start ---------------------------------
    # Not required: a pre-launch company can register by name alone.
    FieldSpec("website", "Website", "Company", "domain",
              hint="The one link we research from."),
    FieldSpec("email", "Work email", "Company", "exact", required=True, founder_only=True,
              hint="Should be on the company domain."),
    FieldSpec("stage", "Stage", "Company", "exact", required=True, founder_only=True),
    # --- what the agent should find --------------------------------------
    FieldSpec("legal_name", "Company name", "Company", "name", required=True),
    FieldSpec("one_liner", "One-liner", "Company", "freeform"),
    FieldSpec("long_description", "Description", "Company", "freeform"),
    FieldSpec("sector", "Sector", "Company", "exact", required=True),
    FieldSpec("sub_vertical", "Sub-vertical", "Company", "freeform"),
    FieldSpec("founded_year", "Founded", "Company", "year", required=True),
    FieldSpec("hq_city", "Headquarters city", "Company", "city", required=True),
    FieldSpec("hq_state", "State / region", "Company", "state"),
    FieldSpec("employee_count", "Team size", "Company", "count"),
    # --- identity & registry ---------------------------------------------
    FieldSpec("cin", "CIN (MCA)", "Registry", "exact",
              hint="Indian companies: unlocks the MCA21 registry check."),
    FieldSpec("gstin", "GSTIN", "Registry", "exact",
              hint="With consent, unlocks the GST revenue cross-check."),
    FieldSpec("domain_registered", "Domain registered", "Registry", "text", readonly=True),
    FieldSpec("mail_provider", "Mail provider", "Registry", "text", readonly=True),
    # --- public presence -------------------------------------------------
    FieldSpec("github_org", "GitHub organisation", "Presence", "exact"),
    FieldSpec("linkedin_url", "LinkedIn page", "Presence", "exact"),
    FieldSpec("twitter_url", "X / Twitter", "Presence", "exact"),
    FieldSpec("total_funding_usd", "Disclosed funding (USD)", "Presence", "money", readonly=True,
              hint="From public funding records in our corpus — partial, not a lifetime total."),
    # Capital actually issued, as filed with the Registrar of Companies. This
    # is the one funding-shaped number that is officially verifiable for an
    # Indian company. It is NOT the money raised: shares are issued at a
    # premium and the premium sits outside paid-up capital, so a company that
    # raised a billion can show a far smaller figure here. Labelled precisely
    # for that reason.
    FieldSpec("paid_up_capital", "Paid-up capital (MCA)", "Registry", "money", readonly=True,
              hint="Share capital issued, as filed with the MCA. Excludes share premium, "
                   "so it is a floor on money raised, not the total."),
    FieldSpec("authorized_capital", "Authorised capital (MCA)", "Registry", "money", readonly=True,
              hint="The ceiling the company may issue up to, as filed with the MCA."),
    # --- founder-only numbers (stage-gated) -------------------------------
    FieldSpec("revenue", "Annual revenue (USD)", "Financials", "money", founder_only=True,
              hint="Cross-checked against GST filings when you consent."),
    FieldSpec("burn_rate_monthly", "Monthly burn (USD)", "Financials", "money", founder_only=True),
    FieldSpec("cash_balance", "Cash in bank (USD)", "Financials", "money", founder_only=True),
    FieldSpec("mrr", "MRR (USD)", "Financials", "money", founder_only=True),
    FieldSpec("active_users", "Active users", "Financials", "count", founder_only=True),
]
SPEC = {f.key: f for f in FIELDS}
FINANCIAL_REQUIRED = ("burn_rate_monthly", "cash_balance")


def _live(ev: dict) -> bool:
    """Independent of the founder: a fresh lookup, or a public dataset."""
    return ev.get("kind") in ("network", "dataset")


def _pick(evidence: list[dict]) -> dict | None:
    """Best evidence to fill a field with: live first, then by source rank."""
    usable = [e for e in evidence if e.get("suggest", True) and e.get("value") not in (None, "")]
    if not usable:
        return None
    rank = {s: i for i, s in enumerate(SOURCE_RANK)}
    kind_rank = {"network": 0, "dataset": 1, "local": 2, "mock": 3}
    return sorted(
        usable,
        key=lambda e: (not e.get("prefer"), kind_rank.get(e.get("kind"), 3), rank.get(e["source"], 99)),
    )[0]


def reconcile(
    inputs: dict[str, Any],
    evidence: dict[str, list[dict]],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    stage = inputs.get("stage")
    rows: list[dict[str, Any]] = []

    for spec in FIELDS:
        if spec.group == "Financials" and stage == "idea":
            continue
        ev = [dict(e) for e in evidence.get(spec.key, [])]
        override = overrides.get(spec.key, {}) if isinstance(overrides.get(spec.key), dict) else {}
        claim = override.get("value") if "value" in override else inputs.get(spec.key)
        claim = None if claim == "" else claim
        origin = "founder" if claim is not None else "agent"

        # `force` lets a check veto a value outright (e.g. a bad GSTIN check digit).
        verdicts = (
            [(e, e.get("force") or compare(e.get("compare_as") or spec.kind, claim, e.get("value"))) for e in ev]
            if claim is not None
            else []
        )
        for e, v in verdicts:
            e["verdict"] = v

        status: str
        value: Any = claim
        suggestion: dict | None = None
        note = ""
        warn = False

        if spec.readonly:
            best = _pick(ev)
            value = best["value"] if best else None
            status = "fetched" if best else "empty"
            origin = "agent"
        elif claim is not None:
            live_agree = [e for e, v in verdicts if v == "agree" and _live(e)]
            live_disagree = [e for e, v in verdicts if v == "disagree" and _live(e)]
            soft_agree = [e for e, v in verdicts if v == "agree" and not _live(e)]
            soft_disagree = [e for e, v in verdicts if v == "disagree" and not _live(e)]
            if live_disagree and not live_agree:
                best = _pick(live_disagree)
                if best and best.get("suggest", True):
                    suggestion = {"value": best["value"], "source": best["source"]}
                note = live_disagree[0].get("note") or ""
                status = "disputed" if override.get("resolution") == "keep" else "conflict"
            elif live_agree:
                status = "verified"
                note = f"Matches {', '.join(sorted({e['label'] for e in live_agree}))}"
            elif any(e.get("blocking") for e in soft_disagree):
                # A failed local check (bad check digit) is a hard stop.
                status = "disputed" if override.get("resolution") == "keep" else "conflict"
                note = next(e for e in soft_disagree if e.get("blocking")).get("note") or ""
            elif soft_disagree:
                status = "claimed"
                warn = True
                note = f"{soft_disagree[0]['label']}: {soft_disagree[0].get('note') or 'disagrees'}" \
                    " — not proof, but flagged for review"
            elif soft_agree:
                status = "claimed"
                note = "Consistent with " + ", ".join(sorted({e["label"] for e in soft_agree})) + \
                    " — supporting, not independent proof"
            else:
                status = "claimed"
                neutral = [e for e, v in verdicts if v == "neutral" and e.get("note")]
                note = neutral[0]["note"] if neutral else (
                    "Your word only — no public source covers this" if spec.founder_only or not ev
                    else "Sources found nothing comparable")
        else:
            best = _pick(ev)
            if best:
                value = best["value"]
                others = [e for e in ev if e is not best and _live(e)]

                def _v(e: dict) -> str:
                    return compare(e.get("compare_as") or spec.kind, value, e.get("value"))

                agree = [e for e in others if _v(e) == "agree"]
                disagree = [e for e in others if _v(e) == "disagree"]
                best["verdict"] = "picked"
                for e in agree:
                    e["verdict"] = "agree"
                for e in disagree:
                    e["verdict"] = "disagree"
                if disagree and _live(best):
                    status = "conflict"
                    alt = _pick([e for e in disagree if e.get("suggest", True)])
                    if alt:
                        suggestion = {"value": alt["value"], "source": alt["source"]}
                    note = f"{best['label']} and {disagree[0]['label']} disagree — pick one"
                elif agree and _live(best):
                    status = "verified"
                    note = f"{best['label']} and {', '.join(sorted({e['label'] for e in agree}))} agree"
                elif best.get("force") == "agree" and _live(best):
                    status = "verified"
                    note = best.get("note") or f"Confirmed by {best['label']}"
                else:
                    status = "fetched"
                    note = f"From {best['label']}" + (" (mocked source)" if best.get("kind") == "mock" else "")
                    alts = len({str(e.get("value")) for e in ev if e.get("suggest", True)} - {str(value)})
                    if spec.kind == "freeform" and alts:
                        note += f" · {alts} other version{'s' if alts > 1 else ''} to choose from"
            else:
                status = "missing" if (spec.required or (
                    spec.key in FINANCIAL_REQUIRED and stage not in (None, "idea"))) else "empty"

        rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "group": spec.group,
                "required": spec.required or (spec.key in FINANCIAL_REQUIRED and stage != "idea"),
                "founder_only": spec.founder_only,
                "readonly": spec.readonly,
                "hint": spec.hint,
                "value": value,
                "origin": origin,
                "status": status,
                "note": note,
                "suggestion": suggestion,
                "warn": warn,
                "evidence": ev,
            }
        )

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    blocking = [r["key"] for r in rows if r["status"] in ("conflict", "missing")]
    return {"fields": rows, "counts": counts, "blocking": blocking}
