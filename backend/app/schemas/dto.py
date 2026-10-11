"""Pydantic v2 request/response models.

The report calls for two validation layers (client Zod, server Pydantic). These
are the server half --- every write endpoint re-validates here regardless of what
the browser already checked.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Stage = Literal["idea", "seed", "series_a", "series_b_plus", "growth"]
RiskTolerance = Literal["low", "medium", "high"]
InvestorType = Literal["angel", "vc_fund", "family_office"]


# --------------------------------------------------------------------------
# Startup input
# --------------------------------------------------------------------------


class FinancialsIn(BaseModel):
    as_of_date: date | None = None
    revenue: float | None = Field(None, ge=0)
    burn_rate_monthly: float | None = Field(None, ge=0)
    cash_balance: float | None = Field(None, ge=0)
    cac: float | None = Field(None, ge=0)
    ltv: float | None = Field(None, ge=0)
    tam_usd: float | None = Field(None, ge=0)
    sam_usd: float | None = Field(None, ge=0)
    active_users: int | None = Field(None, ge=0)
    mrr: float | None = Field(None, ge=0)
    arr: float | None = Field(None, ge=0)
    prior_year_revenue: float | None = Field(None, ge=0)
    total_funding_usd: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def sam_within_tam(self) -> FinancialsIn:
        if self.tam_usd and self.sam_usd and self.sam_usd > self.tam_usd:
            raise ValueError("sam_usd cannot exceed tam_usd")
        return self


class FounderIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    role: str | None = None
    linkedin_url: str | None = None
    github_username: str | None = None


class StartupIn(BaseModel):
    """Stage-aware. An idea-stage startup has no burn rate to report, so the
    financial block is optional there and required from seed onward --- this is
    the server-side mirror of the conditional form (report section 8.1.1).
    """

    legal_name: str = Field(min_length=2, max_length=255)
    stage: Stage
    sector: str = Field(min_length=2, max_length=96)
    sub_vertical: str | None = None
    founded_date: date | None = None
    yc_batch: str | None = None
    hq_city: str | None = None
    hq_state: str | None = None
    website: str | None = None
    cin: str | None = None
    gstin: str | None = None
    one_liner: str | None = Field(None, max_length=280)
    long_description: str | None = None
    employee_count: int | None = Field(None, ge=0)
    founders: list[FounderIn] = Field(default_factory=list)
    financials: FinancialsIn | None = None

    @model_validator(mode="after")
    def stage_conditional_requirements(self) -> StartupIn:
        if self.stage == "idea":
            return self
        f = self.financials
        if f is None:
            raise ValueError(f"stage '{self.stage}' requires a financials block")
        missing = [k for k in ("burn_rate_monthly", "cash_balance") if getattr(f, k) is None]
        if missing:
            raise ValueError(
                f"stage '{self.stage}' requires financial fields: {', '.join(missing)}"
            )
        return self


# --------------------------------------------------------------------------
# Startup output
# --------------------------------------------------------------------------


class FounderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    founder_id: str
    name: str
    name_source: str | None = None
    role: str | None = None
    linkedin_url: str | None = None
    github_username: str | None = None
    prior_exits: int | None = None
    domain_experience_years: float | None = None
    github_commit_count_90d: int | None = None
    github_followers: int | None = None


class FinancialsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date | None = None
    revenue: float | None = None
    burn_rate_monthly: float | None = None
    cash_balance: float | None = None
    runway_months: float | None = None
    cac: float | None = None
    ltv: float | None = None
    ltv_cac_ratio: float | None = None
    tam_usd: float | None = None
    sam_usd: float | None = None
    active_users: int | None = None
    mrr: float | None = None
    arr: float | None = None
    revenue_growth_pct: float | None = None
    total_funding_usd: float | None = None
    gst_reported_revenue: float | None = None


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score_id: str
    growth_potential_score: float
    risk_level_score: float
    fraud_likelihood_score: float
    founder_credibility_score: float
    composite_score: float
    shap_top_features: dict[str, Any] | None = None
    rationale: dict[str, Any] | None = None
    confidence: str
    cohort_size: int | None = None
    model_version: str
    computed_at: datetime


class FraudSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signal_id: str
    detector: str
    anomaly_score: float
    reconstruction_error: float | None = None
    flagged_fields: list[Any] | None = None
    severity: str
    explanation: str | None = None
    reviewed_by_human: bool
    run_at: datetime


class EnrichmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enrichment_id: str
    source: str
    is_mock: bool
    status: str
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    retrieved_at: datetime


class StartupSummary(BaseModel):
    """Row shape for lists and the investor feed --- deliberately light."""

    model_config = ConfigDict(from_attributes=True)

    startup_id: str
    legal_name: str
    logo_url: str | None = None
    stage: str
    sector: str
    sub_vertical: str | None = None
    hq_city: str | None = None
    one_liner: str | None = None
    employee_count: int | None = None
    status: str | None = None
    verified: bool
    source: str
    composite_score: float | None = None
    growth_potential_score: float | None = None
    risk_level_score: float | None = None
    fraud_likelihood_score: float | None = None
    founder_credibility_score: float | None = None
    total_funding_usd: float | None = None


class StartupDetail(StartupSummary):
    long_description: str | None = None
    website: str | None = None
    hq_state: str | None = None
    founded_date: date | None = None
    yc_batch: str | None = None
    owned_by_me: bool = False
    logo_source: str | None = None
    company_linkedin_url: str | None = None
    company_twitter_url: str | None = None
    company_github_org: str | None = None
    cin: str | None = None
    gstin: str | None = None
    created_at: datetime
    founders: list[FounderOut] = Field(default_factory=list)
    financials: FinancialsOut | None = None
    score: ScoreOut | None = None
    fraud_signals: list[FraudSignalOut] = Field(default_factory=list)
    enrichments: list[EnrichmentOut] = Field(default_factory=list)


class PaginatedStartups(BaseModel):
    items: list[StartupSummary]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------
# Investor
# --------------------------------------------------------------------------


class PreferenceIn(BaseModel):
    ticket_size_min: float | None = Field(None, ge=0)
    ticket_size_max: float | None = Field(None, ge=0)
    stage_preference: list[Stage] = Field(default_factory=list)
    preferred_sectors: list[str] = Field(default_factory=list)
    geographic_preference: list[str] = Field(default_factory=list)
    risk_tolerance: RiskTolerance = "medium"

    @model_validator(mode="after")
    def ticket_range_ordered(self) -> PreferenceIn:
        lo, hi = self.ticket_size_min, self.ticket_size_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("ticket_size_min cannot exceed ticket_size_max")
        return self


class InvestorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: str | None = None
    investor_type: InvestorType
    firm_name: str | None = None
    sebi_registration_no: str | None = None
    accredited_investor: bool = False
    preference: PreferenceIn | None = None


class PreferenceOut(PreferenceIn):
    model_config = ConfigDict(from_attributes=True)


class InvestorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    investor_id: str
    name: str
    email: str | None = None
    investor_type: str
    firm_name: str | None = None
    kyc_status: str
    accredited_investor: bool
    created_at: datetime
    preference: PreferenceOut | None = None


class EventIn(BaseModel):
    investor_id: str
    startup_id: str | None = None
    event_type: Literal[
        "view", "save", "dismiss", "time_spent", "document_view", "interest_expressed"
    ]
    event_value: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Matching / feed
# --------------------------------------------------------------------------


class MatchOut(BaseModel):
    startup: StartupSummary
    match_score: float
    preference_score: float
    behavioral_score: float
    network_score: float
    quality_score: float
    reasons: list[str]
    cold_start: bool


class BenchmarkPeer(BaseModel):
    startup_id: str
    legal_name: str
    sector: str
    stage: str
    similarity: float
    composite_score: float | None = None
    total_funding_usd: float | None = None
    status: str | None = None


class BenchmarkOut(BaseModel):
    startup_id: str
    cohort_size: int
    confidence: str
    peers: list[BenchmarkPeer]
    percentiles: dict[str, float | None]
    narrative: str
