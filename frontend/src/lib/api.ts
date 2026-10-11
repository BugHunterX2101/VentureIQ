// Same-origin "/api" in dev (Vite proxies it) and wherever the API is served
// from the same host. On a static host such as Vercel, set VITE_API_BASE to the
// backend's public URL at build time, e.g. https://api.example.com/api
const BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");

const TOKEN_KEY = "viq.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: the session simply won't persist */
  }
}

/** Raised on 401 so callers can send the visitor to sign in. */
export class Unauthorized extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    setToken(null);
    throw new Unauthorized("Your session has expired — sign in again");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    let structured: unknown = null;
    try {
      const body = await res.json();
      if (body?.detail) {
        structured = body.detail;
        if (typeof body.detail === "string") detail = body.detail;
        else if (Array.isArray(body.detail))
          detail = body.detail.map((d: any) => `${d.loc?.slice(1).join(".")}: ${d.msg}`).join("; ");
        else if (typeof body.detail?.message === "string") detail = body.detail.message;
      }
    } catch {
      /* keep the status line */
    }
    // Endpoints that answer with structured reasons (compliance, for one) keep
    // them on the error so callers can render each rule instead of a blob.
    throw Object.assign(new Error(detail), { detail: structured, status: res.status });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/* ---------------------------------------------------------------- types */

export type Stage = "idea" | "seed" | "series_a" | "series_b_plus" | "growth";

export interface StartupSummary {
  startup_id: string;
  legal_name: string;
  /** The company's own logo, when a real source published one. */
  logo_url?: string | null;
  stage: Stage;
  sector: string;
  sub_vertical: string | null;
  hq_city: string | null;
  one_liner: string | null;
  employee_count: number | null;
  status: string | null;
  verified: boolean;
  source: string;
  composite_score: number | null;
  growth_potential_score: number | null;
  risk_level_score: number | null;
  fraud_likelihood_score: number | null;
  founder_credibility_score: number | null;
  total_funding_usd: number | null;
}

export interface Attribution {
  feature: string;
  value: number | string | null;
  contribution: number;
  direction: "positive" | "negative";
  label: string;
  /** Raw Shapley value in the model's own units, when SHAP produced this row. */
  shap_value?: number | null;
}

export interface ScoreDetail {
  score_id: string;
  growth_potential_score: number;
  risk_level_score: number;
  fraud_likelihood_score: number;
  founder_credibility_score: number;
  composite_score: number;
  shap_top_features: Record<string, { method: string; features: Attribution[] }> | null;
  rationale: Record<string, string> | null;
  confidence: string;
  cohort_size: number | null;
  model_version: string;
  computed_at: string;
}

export interface Founder {
  founder_id: string;
  name: string;
  role: string | null;
  /** Where the name came from. "modelled" means it is a placeholder. */
  name_source?: string | null;
  linkedin_url: string | null;
  github_username: string | null;
  prior_exits: number | null;
  domain_experience_years: number | null;
  github_commit_count_90d: number | null;
  github_followers: number | null;
}

export interface Financials {
  as_of_date: string | null;
  revenue: number | null;
  burn_rate_monthly: number | null;
  cash_balance: number | null;
  runway_months: number | null;
  cac: number | null;
  ltv: number | null;
  ltv_cac_ratio: number | null;
  tam_usd: number | null;
  sam_usd: number | null;
  active_users: number | null;
  revenue_growth_pct: number | null;
  total_funding_usd: number | null;
  gst_reported_revenue: number | null;
}

export interface FraudSignal {
  signal_id: string;
  detector: string;
  anomaly_score: number;
  reconstruction_error: number | null;
  flagged_fields: string[] | null;
  severity: "low" | "medium" | "high";
  explanation: string | null;
  reviewed_by_human: boolean;
  run_at: string;
}

export interface EnrichmentRecord {
  enrichment_id: string;
  source: string;
  is_mock: boolean;
  status: string;
  raw_response: Record<string, any> | null;
  error: string | null;
  retrieved_at: string;
}

export interface StartupDetail extends StartupSummary {
  long_description: string | null;
  website: string | null;
  hq_state: string | null;
  founded_date: string | null;
  /** Y Combinator batch, e.g. "Winter 2022". Not a founding date. */
  yc_batch?: string | null;
  /** True when the signed-in viewer owns this company. */
  owned_by_me?: boolean;
  logo_source?: string | null;
  company_linkedin_url?: string | null;
  company_twitter_url?: string | null;
  company_github_org?: string | null;
  cin: string | null;
  gstin: string | null;
  created_at: string;
  founders: Founder[];
  financials: Financials | null;
  score: ScoreDetail | null;
  fraud_signals: FraudSignal[];
  enrichments: EnrichmentRecord[];
}

export interface Match {
  startup: StartupSummary;
  match_score: number;
  preference_score: number;
  behavioral_score: number;
  network_score: number;
  quality_score: number;
  reasons: string[];
  cold_start: boolean;
}

export interface Investor {
  investor_id: string;
  name: string;
  email: string | null;
  investor_type: string;
  firm_name: string | null;
  kyc_status: string;
  accredited_investor: boolean;
  created_at: string;
  preference: {
    ticket_size_min: number | null;
    ticket_size_max: number | null;
    stage_preference: Stage[];
    preferred_sectors: string[];
    geographic_preference: string[];
    risk_tolerance: string;
  } | null;
}

export interface CompetitorRow extends StartupSummary {
  similarity: number | null;
  founded_year: number | null;
  yc_batch: string | null;
  revenue: number | null;
  runway_months: number | null;
}

export interface CompetitorSet {
  subject: CompetitorRow;
  peers: CompetitorRow[];
  median: Record<string, number | null>;
  basis: string;
}

export interface MentorOffer {
  offer_id: string;
  startup_id: string;
  mentor_name: string;
  mentor_firm: string | null;
  focus_areas: string[];
  status: "offered" | "accepted" | "declined" | "withdrawn";
  public: boolean;
  created_at: string;
  decided_at: string | null;
  /** Only present for the founder and the mentor themselves. */
  message?: string | null;
  hours_per_month?: number | null;
  founder_note?: string | null;
  mentor_email?: string | null;
  startup_name?: string | null;
  startup_sector?: string | null;
}

export interface PlatformStats {
  startups: number;
  scored: number;
  verified: number;
  investors: number;
  behavioral_events: number;
  enrichment_calls: number;
  flagged_startups: number;
  avg_composite_score: number | null;
  total_tracked_funding_usd: number;
}

export interface Benchmark {
  startup_id: string;
  cohort_size: number;
  confidence: string;
  peers: {
    startup_id: string;
    legal_name: string;
    sector: string;
    stage: string;
    similarity: number;
    composite_score: number | null;
    total_funding_usd: number | null;
    status: string | null;
  }[];
  percentiles: Record<string, number | null>;
  narrative: string;
}

/** Column-oriented so ~1,800 points stay small on the wire. */
export interface ConstellationData {
  sectors: string[];
  count: number;
  id: string[];
  name: string[];
  sector: number[];
  score: number[];
  fraud: number[];
  verified: boolean[];
}

/* ---------------------------------------------------------- onboarding */

export type EvidenceKind = "network" | "dataset" | "local" | "mock";
export type FieldStatus = "verified" | "fetched" | "claimed" | "conflict" | "disputed" | "missing" | "empty";

export interface Evidence {
  source: string;
  tool: string;
  label: string;
  kind: EvidenceKind;
  value: any;
  note: string;
  suggest: boolean;
  verdict?: "agree" | "disagree" | "neutral" | "picked";
}

export interface LedgerField {
  key: string;
  label: string;
  group: "Company" | "Registry" | "Presence" | "Financials";
  required: boolean;
  founder_only: boolean;
  readonly: boolean;
  hint: string;
  value: any;
  origin: "founder" | "agent";
  status: FieldStatus;
  note: string;
  suggestion: { value: any; source: string } | null;
  warn: boolean;
  evidence: Evidence[];
}

export interface OnboardFounder {
  name: string;
  role: string | null;
  github: string | null;
  linkedin: string | null;
  source: "founder" | "website";
  check: { status: FieldStatus; note: string; label?: string } | null;
  checks?: { status: FieldStatus; note: string; label: string }[];
}

export interface OnboardSnapshot {
  session_id: string;
  status: "running" | "ready" | "submitted";
  inputs: Record<string, any>;
  ledger: { fields: LedgerField[]; counts: Partial<Record<FieldStatus, number>>; blocking: string[] };
  founders: OnboardFounder[];
  facts: Record<string, any>;
  gst_consent: boolean;
  startup_id: string | null;
}

export type AgentEvent = { seq: number; t: number } & (
  | { type: "start"; domain: string | null }
  | { type: "thought"; text: string }
  | { type: "plan"; id: string; tool: string; label: string; kind: EvidenceKind; reason: string }
  | { type: "step"; id: string; tool: string; status: "running" }
  | { type: "step_done"; id: string; tool: string; ok: boolean; summary: string; ms: number }
  | ({ type: "finding"; field: string; tool: string | null } & Evidence)
  | { type: "done" }
  | { type: "submitted"; startup_id: string }
);

export interface RegistryCompany {
  cin: string;
  name: string;
  status: string | null;
  class: string | null;
  category: string | null;
  registered: string | null;
  state: string | null;
  city: string | null;
  industry: string | null;
  paidup_capital: number | null;
  address: string | null;
  startup_id?: string | null;
  how?: "local" | "live";
}

export interface RegistryStatus {
  available: boolean;
  companies: number;
  source_total?: number | null;
  source_updated?: string | null;
  complete?: boolean;
  source: string;
}

export interface AgentTool {
  id: string;
  label: string;
  kind: EvidenceKind;
  what: string;
  how: string;
  consent: string;
}

export interface AuthUser {
  user_id: string;
  email: string;
  name: string;
  role: "investor" | "founder";
  investor_id: string | null;
  investor_name: string | null;
  kyc_status: string | null;
  has_mandate: boolean;
  /** May act on the KYC queue; the API checks this again on every call. */
  is_reviewer?: boolean;
  watchlist_count: number;
  created_at: string;
}

export interface DocField {
  key: string;
  value: any;
  confidence: number;
  evidence: string;
  note: string;
}

export interface DocCheck {
  check: string;
  status: "verified" | "conflict";
  detail: string;
  source: string;
  kind: EvidenceKind;
}

export interface DocResult {
  document_id?: string;
  filename: string;
  doc_type: string;
  doc_type_label: string;
  type_confidence: number;
  engine: string;
  pages: number;
  ocr_confidence: number | null;
  warnings: string[];
  fields: DocField[];
  checks: DocCheck[];
  text_preview: string;
  snapshot?: OnboardSnapshot;
}

export interface StoredDoc {
  document_id: string;
  doc_type: string;
  doc_type_label: string;
  filename: string;
  uploaded_at: string;
  extraction_confidence: number | null;
  fields: DocField[];
  checks: DocCheck[];
}

export interface KycCheck {
  check: string;
  status: "passed" | "failed" | "review";
  detail: string;
  kind: string;
}

export interface KycCase {
  case_id: string;
  status: "submitted" | "passed_checks" | "failed_checks" | "verified" | "rejected";
  pan: string | null;
  legal_name: string | null;
  document_type: string | null;
  checks: KycCheck[];
  reviewer_note: string | null;
  submitted_at: string;
  decided_at: string | null;
  what_this_means: string;
}

export interface KycStatus {
  case: KycCase | null;
  kyc_status: string | null;
  accredited: boolean;
  marketplace_unlocked: boolean;
  note: string;
}

export interface MarketRule {
  id: string;
  rule: string;
  why: string;
}

export interface ComplianceVerdict {
  id: string;
  passed: boolean;
  detail: string;
  rule: string;
  why: string;
}

export interface MarketOffer {
  offer_id: string;
  listing_id: string;
  amount: number;
  equity_pct: number | null;
  message: string | null;
  status: string;
  compliance: { verdicts: ComplianceVerdict[] } | null;
  rofr_expires_at: string | null;
  created_at: string;
  simulated: boolean;
  startup: { startup_id: string; legal_name: string } | null;
  ask_amount: number | null;
  next?: string;
  settlement?: { simulated: boolean; note: string };
}

export interface MyStartup {
  startup_id: string;
  legal_name: string;
  sector: string;
  stage: Stage;
  hq_city: string | null;
  website: string | null;
  cin: string | null;
  verified: boolean;
  created_at: string;
  composite_score: number | null;
  growth_potential_score: number | null;
  risk_level_score: number | null;
  fraud_likelihood_score: number | null;
  founder_credibility_score: number | null;
  confidence: string | null;
  scored_at: string | null;
  open_flags: number;
  top_flag: string | null;
}

export interface WatchlistItem {
  item_id: string;
  startup_id: string;
  note: string | null;
  stage: "watching" | "contacted" | "passed";
  created_at: string;
  startup: {
    startup_id: string;
    legal_name: string;
    logo_url?: string | null;
    sector: string;
    stage: Stage;
    hq_city: string | null;
    verified: boolean;
    composite_score: number | null;
    fraud_likelihood_score: number | null;
  } | null;
}

export interface Alert {
  signal_id: string;
  startup_id: string;
  startup_name: string;
  sector: string;
  detector: string;
  severity: string;
  anomaly_score: number;
  explanation: string;
  flagged_fields: string[] | null;
  reviewed_by_human: boolean;
  run_at: string;
}

/* ---------------------------------------------------------------- calls */

export const api = {
  health: () => request<any>("/health"),
  stats: () => request<PlatformStats>("/stats"),
  sectorStats: () =>
    request<{ sector: string; count: number; avg_composite_score: number | null; avg_fraud_score: number | null }[]>(
      "/stats/sectors",
    ),
  stageStats: () =>
    request<{ stage: string; count: number; avg_composite_score: number | null }[]>("/stats/stages"),
  scoreDistribution: () =>
    request<{ bucket: string; lower: number; count: number }[]>("/stats/score-distribution"),
  fundingTimeline: () =>
    request<{ year: number; rounds: number; total_usd: number }[]>("/stats/funding-timeline"),
  cities: () => request<{ city: string; count: number }[]>("/stats/cities"),
  constellation: (limit = 1800) => request<ConstellationData>(`/stats/constellation?limit=${limit}`),
  modelMetrics: () => request<any>("/model/metrics"),
  alerts: (limit = 20) => request<Alert[]>(`/alerts?limit=${limit}`),
  auditLog: (limit = 50) => request<any[]>(`/audit?limit=${limit}`),

  startups: (params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== false) qs.set(k, String(v));
    });
    return request<{ items: StartupSummary[]; total: number; limit: number; offset: number }>(
      `/startups?${qs}`,
    );
  },
  startup: (id: string) => request<StartupDetail>(`/startups/${id}`),
  sectors: () => request<{ sector: string; count: number }[]>("/startups/sectors"),
  createStartup: (body: unknown) =>
    request<StartupDetail>("/startups", { method: "POST", body: JSON.stringify(body) }),
  rescore: (id: string) => request<any>(`/startups/${id}/score`, { method: "POST" }),
  enrich: (id: string, force = false) =>
    request<{ trace: any; score: any }>(`/startups/${id}/enrich?force=${force}`, {
      method: "POST",
    }),
  benchmark: (id: string) => request<Benchmark>(`/startups/${id}/benchmark`),
  similar: (id: string, k = 6) => request<StartupSummary[]>(`/startups/${id}/similar?k=${k}`),

  investors: () => request<Investor[]>("/investors"),
  investor: (id: string) => request<Investor>(`/investors/${id}`),
  createInvestor: (body: unknown) =>
    request<Investor>("/investors", { method: "POST", body: JSON.stringify(body) }),
  feed: (id: string, params: Record<string, any> = {}) => {
    const qs = new URLSearchParams({ limit: "24", ...params });
    return request<Match[]>(`/investors/${id}/feed?${qs}`);
  },
  activity: (id: string) => request<any[]>(`/investors/${id}/activity`),

  track: (body: {
    investor_id: string;
    startup_id?: string;
    event_type: string;
    event_value?: Record<string, unknown>;
  }) =>
    // Fire-and-forget: behavioural tracking must never block the UI. The
    // backend mirrors this with a 202 and no body.
    fetch(`${BASE}/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // This path bypasses request() for keepalive, so it carries the token itself.
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => undefined),

  register: (body: {
    email: string;
    password: string;
    name: string;
    role: "investor" | "founder";
    investor_type?: string;
    firm_name?: string | null;
  }) => request<{ access_token: string; user: AuthUser }>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (email: string, password: string) =>
    request<{ access_token: string; user: AuthUser }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<AuthUser>("/auth/me"),
  authProviders: () => request<{ password: boolean; google: boolean }>("/auth/providers"),
  /** Full-page redirect: Google needs a real navigation, not fetch. */
  googleSignInUrl: (role: "investor" | "founder", next: string) =>
    `${BASE}/auth/google/start?role=${role}&next=${encodeURIComponent(next)}`,
  updateMe: (body: { name?: string; current_password?: string; new_password?: string }) =>
    request<AuthUser>("/auth/me", { method: "PATCH", body: JSON.stringify(body) }),
  setMandate: (body: unknown) =>
    request<AuthUser>("/auth/me/mandate", { method: "PUT", body: JSON.stringify(body) }),
  myStartups: () => request<MyStartup[]>("/auth/me/startups"),
  kycStatus: () => request<KycStatus>("/kyc/me"),
  kycSubmit: async (pan: string, legalName: string, file?: File | null) => {
    const body = new FormData();
    body.append("pan", pan);
    body.append("legal_name", legalName);
    if (file) body.append("file", file);
    const token = getToken();
    const res = await fetch(`${BASE}/kyc/submit`, {
      method: "POST",
      body,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
    return (await res.json()) as KycCase;
  },
  kycQueue: () =>
    request<(KycCase & { submitted_by?: { name: string | null; email: string | null } })[]>(
      "/kyc/queue",
    ),
  kycDecide: (caseId: string, approve: boolean, note?: string) =>
    request<KycCase>(`/kyc/${caseId}/decide?approve=${approve}${note ? `&note=${encodeURIComponent(note)}` : ""}`, {
      method: "POST",
    }),

  mandatePreview: (q: { sectors: string[]; stages: string[]; cities: string[] }) => {
    const p = new URLSearchParams();
    q.sectors.forEach((s) => p.append("sectors", s));
    q.stages.forEach((s) => p.append("stages", s));
    q.cities.forEach((c) => p.append("cities", c));
    return request<{
      matches: number;
      sample: { startup_id: string; legal_name: string; sector: string; hq_city: string | null; composite_score: number | null }[];
    }>(`/investors/mandate/preview?${p.toString()}`);
  },
  competitors: (id: string, k = 8) => request<CompetitorSet>(`/startups/${id}/competitors?k=${k}`),
  mentorFocusAreas: () => request<{ focus_areas: string[] }>("/mentorship/focus-areas"),
  mentorsOf: (startupId: string) =>
    request<{ mentors: MentorOffer[]; my_offer: MentorOffer | null }>(
      `/mentorship/startups/${startupId}/mentors`,
    ),
  offerMentorship: (body: {
    startup_id: string;
    message?: string | null;
    focus_areas: string[];
    hours_per_month?: number | null;
  }) => request<MentorOffer>("/mentorship/offers", { method: "POST", body: JSON.stringify(body) }),
  withdrawMentorship: (offerId: string) =>
    request<void>(`/mentorship/offers/${offerId}`, { method: "DELETE" }),
  mentorshipInbox: (startupId: string) =>
    request<MentorOffer[]>(`/mentorship/startups/${startupId}/offers`),
  decideMentorship: (offerId: string, body: { accept: boolean; public?: boolean; founder_note?: string }) =>
    request<MentorOffer>(`/mentorship/offers/${offerId}/decide`, { method: "POST", body: JSON.stringify(body) }),
  setMentorVisibility: (offerId: string, isPublic: boolean) =>
    request<MentorOffer>(`/mentorship/offers/${offerId}/visibility?public=${isPublic}`, { method: "PATCH" }),

  marketRules: () =>
    request<{ simulated: boolean; disclaimer: string; accredited_threshold_usd: number; rules: MarketRule[] }>(
      "/marketplace/rules",
    ),
  listings: () => request<{ disclaimer: string; items: any[] }>("/marketplace/listings"),
  createListing: (startupId: string, ask: number, equityPct: number, rofrDays = 7) =>
    request<any>(
      `/marketplace/listings?startup_id=${startupId}&ask_amount=${ask}&equity_offered_pct=${equityPct}&rofr_days=${rofrDays}`,
      { method: "POST" },
    ),
  makeOffer: (listingId: string, body: { amount: number; equity_pct?: number | null; message?: string | null }) =>
    request<MarketOffer>(`/marketplace/listings/${listingId}/offers`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  myOffers: () => request<MarketOffer[]>("/marketplace/offers"),
  offerAction: (offerId: string, action: "accept" | "decline" | "settle") =>
    request<MarketOffer>(`/marketplace/offers/${offerId}/${action}`, { method: "POST" }),
  docCapabilities: () =>
    request<{ ocr_available: boolean; detail: string; max_file_mb: number; accepted: string[]; checks: string[] }>(
      "/documents/capabilities",
    ),
  startupDocuments: (id: string) => request<StoredDoc[]>(`/startups/${id}/documents`),
  /** Multipart upload: the browser sets its own Content-Type boundary. */
  uploadDocument: async (target: { startupId?: string; sessionId?: string }, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const token = getToken();
    const path = target.startupId
      ? `/startups/${target.startupId}/documents`
      : `/onboarding/sessions/${target.sessionId}/documents`;
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      body,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const b = await res.json();
        if (b?.detail) detail = typeof b.detail === "string" ? b.detail : detail;
      } catch {
        /* keep the status line */
      }
      throw new Error(detail);
    }
    return (await res.json()) as DocResult;
  },
  watchlist: () => request<WatchlistItem[]>("/auth/me/watchlist"),
  watch: (startup_id: string, body: { note?: string | null; stage?: string } = {}) =>
    request<WatchlistItem>("/auth/me/watchlist", {
      method: "POST",
      body: JSON.stringify({ startup_id, ...body }),
    }),
  unwatch: (startup_id: string) =>
    request<void>(`/auth/me/watchlist/${startup_id}`, { method: "DELETE" }),

  registryStatus: () => request<RegistryStatus>("/registry/status"),
  registrySearch: (q: string, opts: { limit?: number; active_only?: boolean; state?: string } = {}) => {
    const qs = new URLSearchParams({ q, limit: String(opts.limit ?? 8) });
    if (opts.active_only) qs.set("active_only", "true");
    if (opts.state) qs.set("state", opts.state);
    return request<{ items: RegistryCompany[]; source: string; registry: { companies: number; complete: boolean } }>(
      `/registry/search?${qs}`,
    );
  },

  onboardTools: () => request<{ tools: AgentTool[] }>("/onboarding/tools"),
  onboardStart: (body: Record<string, unknown>) =>
    request<{ session_id: string }>("/onboarding/sessions", { method: "POST", body: JSON.stringify(body) }),
  onboardSnapshot: (id: string) => request<OnboardSnapshot>(`/onboarding/sessions/${id}`),
  /** Live trace. The caller closes the stream when `onSnapshot` fires. */
  onboardEvents: (
    id: string,
    h: { onEvent: (e: AgentEvent) => void; onState: (s: OnboardSnapshot) => void; onSnapshot: (s: OnboardSnapshot) => void; onError: () => void },
  ) => {
    const es = new EventSource(`${BASE}/onboarding/sessions/${id}/events`);
    es.onmessage = (m) => h.onEvent(JSON.parse(m.data));
    es.addEventListener("state", (m) => h.onState(JSON.parse((m as MessageEvent).data)));
    es.addEventListener("snapshot", (m) => {
      es.close();
      h.onSnapshot(JSON.parse((m as MessageEvent).data));
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) h.onError();
    };
    return () => es.close();
  },
  onboardEdit: (id: string, edits: { key: string; value?: unknown; resolution?: "accept" | "keep" }[]) =>
    request<OnboardSnapshot>(`/onboarding/sessions/${id}/fields`, { method: "PATCH", body: JSON.stringify(edits) }),
  onboardFounders: (id: string, founders: Omit<OnboardFounder, "source" | "check">[]) =>
    request<OnboardSnapshot>(`/onboarding/sessions/${id}/founders`, { method: "PUT", body: JSON.stringify(founders) }),
  onboardCheckFounder: (id: string, i: number) =>
    request<OnboardSnapshot>(`/onboarding/sessions/${id}/founders/${i}/check`, { method: "POST" }),
  onboardSubmit: (id: string) =>
    request<{ startup_id: string }>(`/onboarding/sessions/${id}/submit`, { method: "POST" }),

  valuation: (id: string) => request<any>(`/marketplace/valuation/${id}`),
};
