"""ORM models implementing docs/DATA_SCHEMA.md.

Field names and semantics track that document. Where the schema marks a field
as enrichment-only (lock icon) or derived, that is noted in a comment here so
nobody wires it to a founder-editable form field by accident.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    UniqueConstraint,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Startup side
# --------------------------------------------------------------------------


class Startup(Base):
    __tablename__ = "startup"

    startup_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    legal_name: Mapped[str] = mapped_column(String(255), index=True)
    slug: Mapped[str | None] = mapped_column(String(255), index=True)

    # Enrichment-verified identifiers --- never trusted from the form alone.
    cin: Mapped[str | None] = mapped_column(String(32))
    gstin: Mapped[str | None] = mapped_column(String(32))

    stage: Mapped[str] = mapped_column(String(32), index=True)  # idea|seed|series_a|...
    sector: Mapped[str] = mapped_column(String(96), index=True)
    sub_vertical: Mapped[str | None] = mapped_column(String(160))

    founded_date: Mapped[datetime | None] = mapped_column(Date)
    # The Y Combinator directory gives an accelerator batch ("Winter 2022") and
    # no founding year. Storing the batch year as `founded_date` said BharatX
    # was founded in 2022 when it was founded in 2019, and the interface
    # presented that as verified. The batch is kept here as what it is, and
    # `founded_date` stays empty for these companies until a source gives one.
    yc_batch: Mapped[str | None] = mapped_column(String(32))
    # The company's own mark, from a source that actually publishes one: the YC
    # directory for YC companies, or the company's own site. Never generated,
    # so a missing logo stays missing and the initials tile stands in.
    logo_url: Mapped[str | None] = mapped_column(String(512))
    logo_source: Mapped[str | None] = mapped_column(String(48))
    linkedin_url: Mapped[str | None] = mapped_column(String(512))
    twitter_url: Mapped[str | None] = mapped_column(String(512))
    github_org: Mapped[str | None] = mapped_column(String(96))
    profile_source: Mapped[str | None] = mapped_column(String(48))
    hq_city: Mapped[str | None] = mapped_column(String(96), index=True)
    hq_state: Mapped[str | None] = mapped_column(String(96))
    registered_address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(512))

    one_liner: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    employee_count: Mapped[int | None] = mapped_column(Integer)

    # Outcome label. Populated for imported historical companies (YC has real
    # labels); null for live registrations, which have not resolved yet.
    status: Mapped[str | None] = mapped_column(String(32), index=True)

    source: Mapped[str] = mapped_column(String(32), default="registration")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # The founder account that registered this company, when there was one.
    owner_user_id: Mapped[str | None] = mapped_column(String(36), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    financials: Mapped[list[StartupFinancials]] = relationship(
        back_populates="startup", cascade="all, delete-orphan"
    )
    founders: Mapped[list[Founder]] = relationship(
        back_populates="startup", cascade="all, delete-orphan"
    )
    documents: Mapped[list[StartupDocument]] = relationship(
        back_populates="startup", cascade="all, delete-orphan"
    )
    enrichments: Mapped[list[EnrichmentRecord]] = relationship(
        back_populates="startup", cascade="all, delete-orphan"
    )
    fraud_signals: Mapped[list[FraudSignal]] = relationship(
        back_populates="startup", cascade="all, delete-orphan"
    )
    scores: Mapped[list[Score]] = relationship(
        back_populates="startup", cascade="all, delete-orphan"
    )

    @property
    def latest_financials(self) -> StartupFinancials | None:
        if not self.financials:
            return None
        return max(self.financials, key=lambda f: f.as_of_date or datetime.min.date())

    @property
    def latest_score(self) -> Score | None:
        if not self.scores:
            return None
        current = [s for s in self.scores if s.is_current]
        return max(current or self.scores, key=lambda s: s.computed_at)


class StartupFinancials(Base):
    __tablename__ = "startup_financials"

    financial_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    as_of_date: Mapped[datetime | None] = mapped_column(Date)

    revenue: Mapped[float | None] = mapped_column(Float)
    burn_rate_monthly: Mapped[float | None] = mapped_column(Float)
    cash_balance: Mapped[float | None] = mapped_column(Float)
    cac: Mapped[float | None] = mapped_column(Float)
    ltv: Mapped[float | None] = mapped_column(Float)
    tam_usd: Mapped[float | None] = mapped_column(Float)
    sam_usd: Mapped[float | None] = mapped_column(Float)
    active_users: Mapped[int | None] = mapped_column(Integer)
    mrr: Mapped[float | None] = mapped_column(Float)
    arr: Mapped[float | None] = mapped_column(Float)
    prior_year_revenue: Mapped[float | None] = mapped_column(Float)
    total_funding_usd: Mapped[float | None] = mapped_column(Float)

    # Enrichment-only: cross-checked against GSTN filings, compared to `revenue`.
    gst_reported_revenue: Mapped[float | None] = mapped_column(Float)

    startup: Mapped[Startup] = relationship(back_populates="financials")

    @property
    def runway_months(self) -> float | None:
        """Derived --- never accepted from the form."""
        if not self.burn_rate_monthly or self.burn_rate_monthly <= 0:
            return None
        return round((self.cash_balance or 0) / self.burn_rate_monthly, 1)

    @property
    def ltv_cac_ratio(self) -> float | None:
        if not self.cac or self.cac <= 0 or self.ltv is None:
            return None
        return round(self.ltv / self.cac, 2)

    @property
    def revenue_growth_pct(self) -> float | None:
        if not self.prior_year_revenue or self.prior_year_revenue <= 0:
            return None
        return round(((self.revenue or 0) - self.prior_year_revenue) / self.prior_year_revenue * 100, 1)


class Founder(Base):
    __tablename__ = "founder"

    founder_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str | None] = mapped_column(String(96))
    linkedin_url: Mapped[str | None] = mapped_column(String(512))
    github_username: Mapped[str | None] = mapped_column(String(96))

    # Everything below is enrichment-only.
    linkedin_employment_history: Mapped[dict | None] = mapped_column(JSON)
    prior_exits: Mapped[int | None] = mapped_column(Integer)
    domain_experience_years: Mapped[float | None] = mapped_column(Float)
    github_commit_count_90d: Mapped[int | None] = mapped_column(Integer)
    github_contributor_count: Mapped[int | None] = mapped_column(Integer)
    github_followers: Mapped[int | None] = mapped_column(Integer)
    linkedin_endorsement_count: Mapped[int | None] = mapped_column(Integer)
    # Where the NAME came from. "modelled" means we never collected this
    # person and the row is a placeholder carrying synthetic signals; anything
    # else names a real source, and only those are shown as real people.
    name_source: Mapped[str | None] = mapped_column(String(48))

    startup: Mapped[Startup] = relationship(back_populates="founders")


class StartupDocument(Base):
    __tablename__ = "startup_document"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(48))
    filename: Mapped[str | None] = mapped_column(String(512))
    s3_key: Mapped[str | None] = mapped_column(String(512))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    layoutlm_entities: Mapped[dict | None] = mapped_column(JSON)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    deviation_flags: Mapped[list | None] = mapped_column(JSON)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    startup: Mapped[Startup] = relationship(back_populates="documents")


class EnrichmentRecord(Base):
    """One row per agentic source call. Cached for `enrichment_cache_days`."""

    __tablename__ = "enrichment_record"

    enrichment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # github|mca21|gstn|linkedin|whois
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    query_params: Mapped[dict | None] = mapped_column(JSON)
    raw_response: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))  # success|failed|cached_fallback
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    startup: Mapped[Startup] = relationship(back_populates="enrichments")


class FraudSignal(Base):
    __tablename__ = "fraud_signal"

    signal_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    detector: Mapped[str] = mapped_column(String(48))  # isolation_forest|autoencoder|rule
    anomaly_score: Mapped[float] = mapped_column(Float)
    reconstruction_error: Mapped[float | None] = mapped_column(Float)
    flagged_fields: Mapped[list | None] = mapped_column(JSON)
    severity: Mapped[str] = mapped_column(String(16), default="low")  # low|medium|high
    explanation: Mapped[str | None] = mapped_column(Text)
    reviewed_by_human: Mapped[bool] = mapped_column(Boolean, default=False)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    startup: Mapped[Startup] = relationship(back_populates="fraud_signals")


class Score(Base):
    """Four independent scores plus a weighted composite.

    Kept independent deliberately --- report section 8.3 cites the Maarouf et al.
    ablation showing early fusion underperforms. Do not refactor into one head.
    """

    __tablename__ = "score"

    score_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)

    growth_potential_score: Mapped[float] = mapped_column(Float)
    risk_level_score: Mapped[float] = mapped_column(Float)
    fraud_likelihood_score: Mapped[float] = mapped_column(Float)
    founder_credibility_score: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)

    # Top-3 contributing features per score, plus generated text rationale.
    shap_top_features: Mapped[dict | None] = mapped_column(JSON)
    rationale: Mapped[dict | None] = mapped_column(JSON)

    confidence: Mapped[str] = mapped_column(String(16), default="high")  # high|low
    cohort_size: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(48))
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # Scoring appends rather than overwrites, so a startup keeps its scoring
    # history. Exactly one row per startup is the current one; SQL that joins
    # this table must filter on it, or a rescored startup counts several times
    # in aggregates and sorts on whichever old row the planner happens to pick.
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    startup: Mapped[Startup] = relationship(back_populates="scores")


# --------------------------------------------------------------------------
# Investor side
# --------------------------------------------------------------------------


class Investor(Base):
    __tablename__ = "investor"

    investor_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    investor_type: Mapped[str] = mapped_column(String(32))  # angel|vc_fund|family_office
    firm_name: Mapped[str | None] = mapped_column(String(200))
    sebi_registration_no: Mapped[str | None] = mapped_column(String(64))
    kyc_status: Mapped[str] = mapped_column(String(24), default="pending")
    accredited_investor: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    preference: Mapped[InvestorPreference | None] = relationship(
        back_populates="investor", uselist=False, cascade="all, delete-orphan"
    )
    events: Mapped[list[BehavioralEvent]] = relationship(
        back_populates="investor", cascade="all, delete-orphan"
    )


class InvestorPreference(Base):
    __tablename__ = "investor_preference"

    investor_id: Mapped[str] = mapped_column(
        ForeignKey("investor.investor_id"), primary_key=True
    )
    ticket_size_min: Mapped[float | None] = mapped_column(Float)
    ticket_size_max: Mapped[float | None] = mapped_column(Float)
    stage_preference: Mapped[list | None] = mapped_column(JSON)
    preferred_sectors: Mapped[list | None] = mapped_column(JSON)
    geographic_preference: Mapped[list | None] = mapped_column(JSON)
    risk_tolerance: Mapped[str] = mapped_column(String(16), default="medium")

    investor: Mapped[Investor] = relationship(back_populates="preference")


class BehavioralEvent(Base):
    """Kafka-stream equivalent. In the report this arrives via Kafka and lands
    in `event_log`; at MVP scale we write straight to the table and keep the
    same shape so a Kafka producer can be dropped in front later.
    """

    __tablename__ = "behavioral_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investor_id: Mapped[str] = mapped_column(ForeignKey("investor.investor_id"), index=True)
    startup_id: Mapped[str | None] = mapped_column(
        ForeignKey("startup.startup_id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    event_value: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    investor: Mapped[Investor] = relationship(back_populates="events")


class FundingRound(Base):
    """Historical funding events --- seeded from the Indian funding CSVs and used
    to build the co-investment graph.
    """

    __tablename__ = "funding_round"

    round_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    round_stage: Mapped[str | None] = mapped_column(String(64))
    amount_usd: Mapped[float | None] = mapped_column(Float)
    announced_date: Mapped[datetime | None] = mapped_column(Date)
    investor_names: Mapped[list | None] = mapped_column(JSON)


class Listing(Base):
    """Marketplace listing.

    NOTE: escrow/settlement here is a SIMULATION. Real escrow and equity
    transfer are SEBI/RBI-regulated activity --- see docs/BUILD_PLAN.md Problem 1.
    No real payment rail is or should be wired to this table.
    """

    __tablename__ = "listing"

    listing_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    ask_amount: Mapped[float] = mapped_column(Float)
    equity_offered_pct: Mapped[float | None] = mapped_column(Float)
    fair_value_estimate: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="open")
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rofr_days: Mapped[int] = mapped_column(Integer, default=7)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class User(Base):
    """A login. Investors own an `investor` row; founders own the startups they
    register. Role is authoritative here, never on the token alone."""

    __tablename__ = "app_user"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(16), default="investor")  # investor|founder
    auth_provider: Mapped[str] = mapped_column(String(24), default="password")
    provider_subject: Mapped[str | None] = mapped_column(String(255), index=True)
    investor_id: Mapped[str | None] = mapped_column(ForeignKey("investor.investor_id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    investor: Mapped[Investor | None] = relationship()
    watchlist: Mapped[list[WatchlistItem]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class WatchlistItem(Base):
    """A company a user is tracking, with an optional private note."""

    __tablename__ = "watchlist_item"
    __table_args__ = (UniqueConstraint("user_id", "startup_id", name="uq_watchlist_user_startup"),)

    item_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(24), default="watching")  # watching|contacted|passed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped[User] = relationship(back_populates="watchlist")
    startup: Mapped[Startup] = relationship()


class KycCase(Base):
    """One identity-verification attempt (report Layer 1: Auth & KYC).

    What is real here: the document is read, the PAN's format and embedded
    details are checked, and the name on it is compared with the account. What
    is NOT real: the identity decision itself. A licensed provider (or
    DigiLocker/Aadhaar e-KYC under the right contracts) makes that call, so
    `status` stops at `passed_checks` until a human reviewer signs it off.
    """

    __tablename__ = "kyc_case"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.user_id"), index=True)
    investor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    pan: Mapped[str | None] = mapped_column(String(16))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    document_path: Mapped[str | None] = mapped_column(String(512))
    document_type: Mapped[str | None] = mapped_column(String(48))
    checks: Mapped[list | None] = mapped_column(JSON)
    # submitted -> passed_checks | failed_checks -> verified | rejected
    status: Mapped[str] = mapped_column(String(24), default="submitted", index=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class Offer(Base):
    """An expression of interest against a listing. SIMULATED throughout:
    no money moves, and escrow is a state machine, not a payment rail."""

    __tablename__ = "offer"

    offer_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listing.listing_id"), index=True)
    investor_id: Mapped[str] = mapped_column(ForeignKey("investor.investor_id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    amount: Mapped[float] = mapped_column(Float)
    equity_pct: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)
    # offered -> accepted|declined -> (rofr_window) -> escrow_simulated -> settled_simulated
    status: Mapped[str] = mapped_column(String(32), default="offered", index=True)
    compliance: Mapped[dict | None] = mapped_column(JSON)
    rofr_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class OnboardingSession(Base):
    """One agentic registration attempt, before it becomes a Startup.

    Holds what the founder typed, everything the agent found (with per-source
    provenance), the live event log, and the founder's edits. Kept after
    submission so the reconciliation that produced a profile stays auditable.
    """

    __tablename__ = "onboarding_session"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|ready|submitted
    inputs: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict | None] = mapped_column(JSON)  # field -> [evidence]
    overrides: Mapped[dict | None] = mapped_column(JSON)  # founder edits and resolutions
    tool_results: Mapped[dict | None] = mapped_column(JSON)  # tool -> raw payload
    events: Mapped[list | None] = mapped_column(JSON)
    startup_id: Mapped[str | None] = mapped_column(String(36))
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(96))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[dict | None] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class MentorshipOffer(Base):
    """Someone offering to mentor a company, and the founder's answer.

    Distinct from an investment offer on purpose: money and advice travel
    separately, and an investor who is not writing a cheque may still be the
    most useful person on a cap table. No money, no equity, no compliance
    gate --- the founder simply accepts or declines.

    `public` is the founder's call, taken at the moment they accept: an
    accepted mentor appears on the company's public profile only if the
    founder said so. A declined or pending offer is never public, and only the
    two parties can see it.
    """

    __tablename__ = "mentorship_offer"
    __table_args__ = (
        UniqueConstraint("mentor_user_id", "startup_id", name="uq_mentor_startup"),
    )

    offer_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    startup_id: Mapped[str] = mapped_column(ForeignKey("startup.startup_id"), index=True)
    mentor_user_id: Mapped[str] = mapped_column(ForeignKey("app_user.user_id"), index=True)

    # What the mentor is offering, in their own words, plus a short tag list
    # ("go-to-market", "hiring") so a founder can scan a queue of them.
    message: Mapped[str | None] = mapped_column(Text)
    focus_areas: Mapped[list | None] = mapped_column(JSON)
    hours_per_month: Mapped[int | None] = mapped_column(Integer)

    # offered -> accepted | declined, or withdrawn by the mentor.
    status: Mapped[str] = mapped_column(String(16), default="offered", index=True)
    public: Mapped[bool] = mapped_column(Boolean, default=False)
    founder_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)

    startup: Mapped[Startup] = relationship()
    mentor: Mapped[User] = relationship()
