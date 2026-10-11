import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { m } from "motion/react";
import DocumentUpload from "../components/DocumentUpload";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../lib/auth";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api, type Benchmark, type StartupDetail as Detail, type StartupSummary } from "../lib/api";
import {
  compactNum,
  compactUsd,
  fraudBand,
  relativeTime,
  scoreBand,
  stageLabel,
  titleCase,
} from "../lib/format";
import { AttributionBars } from "../components/charts";
import {
  Badge,
  Card,
  Empty,
  LogoTile,
  ProvenanceDot,
  ScoreRing,
  SectionError,
  SectionHeader,
  Spinner,
  VerifiedBadge,
} from "../components/primitives";
import { useInvestor } from "../lib/investor-context";
import { MentorsPanel } from "../components/Mentorship";
import Competitors from "../components/Competitors";

const DIMENSIONS = [
  { key: "growth_potential", label: "Growth potential", scoreKey: "growth_potential_score" },
  { key: "risk_level", label: "Safety", scoreKey: "risk_level_score" },
  { key: "founder_credibility", label: "Founder credibility", scoreKey: "founder_credibility_score" },
  { key: "fraud_likelihood", label: "Fraud likelihood", scoreKey: "fraud_likelihood_score" },
] as const;

const TABS = [
  { id: "summary", label: "Summary" },
  { id: "scores", label: "Scores" },
  { id: "financials", label: "Financials" },
  { id: "people", label: "People" },
  { id: "signals", label: "Signals" },
  { id: "provenance", label: "Provenance" },
  { id: "peers", label: "Peers" },
];

const SOURCE_LABEL: Record<string, string> = {
  seed_yc: "Y Combinator directory",
  seed_india_funding: "Indian funding records",
  registration: "Founder registration",
};

const ENRICH_LABEL: Record<string, string> = {
  mca21: "MCA21",
  gstn: "GSTN",
  github: "GitHub",
  github_org: "GitHub org",
  linkedin: "LinkedIn",
  linkedin_company: "LinkedIn page",
  whois: "Domain (RDAP)",
  website: "Website",
  dns: "DNS",
  email: "Email",
  corpus: "Corpus",
  sector_model: "Sector model",
  cin_check: "CIN check",
  gstin_check: "GSTIN check",
  city_state: "City → state",
};

const SEVERITY_BADGE: Record<string, "critical" | "serious" | "warning"> = {
  high: "critical",
  medium: "serious",
  low: "warning",
};

/** How a score's attributions were produced. `shap:` means exact Shapley
 *  values from the trained tree model; everything else is an additive rule. */
const modelName = (method: string) => method.split(":")[1]?.replace(/_/g, " ") ?? "the model";

function methodBadge(method?: string): string {
  if (!method) return "rules";
  if (method.startsWith("shap:")) return "SHAP";
  if (method.startsWith("model:")) return "ML model";
  return "rules";
}

function methodLabel(method: string): string {
  if (method.startsWith("shap:")) return `SHAP · ${modelName(method)}`;
  if (method.startsWith("model:")) return `Model · ${modelName(method)}`;
  return method.replace(/_/g, " ");
}

function methodTitle(method: string): string {
  if (method.startsWith("shap:"))
    return `Exact Shapley values from the ${modelName(method)} model, grouped by feature and converted to points on this score`;
  if (method.startsWith("model:"))
    return "The model's prediction, without a per-feature decomposition";
  return "Additive rule contributions — each term is its own explanation";
}

function Highlight({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  tone?: string;
}) {
  return (
    <div className="min-w-0 bg-surface px-5 py-4">
      <div className="eyebrow truncate">{label}</div>
      <div className="tnum mt-1 text-[26px] font-semibold leading-tight" style={{ color: tone ?? "var(--color-ink)" }}>
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[12.5px] text-ink-muted">{sub}</div>}
    </div>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="py-3">
      <div className="text-[12.5px] text-ink-muted">{label}</div>
      <div className="tnum mt-0.5 text-[18px] font-semibold" style={{ color: tone ?? "var(--color-ink)" }}>
        {value}
      </div>
      {hint && <div className="text-[11.5px] text-ink-muted">{hint}</div>}
    </div>
  );
}

function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-grid py-2.5 text-[13.5px] last:border-0">
      <span className="shrink-0 text-ink-muted">{k}</span>
      <span className="min-w-0 truncate text-right font-semibold text-ink">{children}</span>
    </div>
  );
}

export default function StartupDetail() {
  const { id } = useParams<{ id: string }>();
  const { track } = useInvestor();
  const [s, setS] = useState<Detail | null>(null);
  const [bench, setBench] = useState<Benchmark | null>(null);
  const [similar, setSimilar] = useState<StartupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [trace, setTrace] = useState<any>(null);
  const [benchErr, setBenchErr] = useState<string | null>(null);
  const [similarErr, setSimilarErr] = useState<string | null>(null);
  const [interested, setInterested] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const toast = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [saved, setSaved] = useState(false);
  const [savePending, setSavePending] = useState(false);

  // Is this company already on the signed-in investor's watchlist?
  useEffect(() => {
    if (!user) {
      setSaved(false);
      return;
    }
    let live = true;
    api
      .watchlist()
      .then((items) => live && setSaved(items.some((i) => i.startup_id === id)))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [user, id]);

  async function toggleSaved() {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(`/startup/${id}`)}`);
      return;
    }
    setSavePending(true);
    const next = !saved;
    try {
      if (next) {
        await api.watch(id!);
        toast({ title: "Saved", body: "It's on your watchlist and will shape your feed.", tone: "good" });
      } else {
        await api.unwatch(id!);
        toast({ title: "Removed from your watchlist" });
      }
      setSaved(next);
    } catch (e) {
      toast({ title: "Couldn't update your watchlist", body: (e as Error).message, tone: "warning" });
    } finally {
      setSavePending(false);
    }
  }
  const [prevScores, setPrevScores] = useState<Record<string, number> | null>(null);
  const [activeDim, setActiveDim] = useState<string>("growth_potential");
  const [activeTab, setActiveTab] = useState("summary");
  const enteredAt = useRef(Date.now());

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setLoadErr(null);
    try {
      const d = await api.startup(id);
      setS(d);
      // Loaded independently: a failed benchmark hides one section, never the page.
      api
        .benchmark(id)
        .then((b) => {
          setBench(b);
          setBenchErr(null);
        })
        .catch((e) => setBenchErr(String(e?.message ?? e)));
      api
        .similar(id, 4)
        .then((r) => {
          setSimilar(r);
          setSimilarErr(null);
        })
        .catch((e) => setSimilarErr(String(e?.message ?? e)));
    } catch (e: any) {
      setLoadErr(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setS(null);
    setBench(null);
    setSimilar([]);
    setTrace(null);
    setPrevScores(null);
    setInterested(false);
    setDismissed(false);
    void load();
  }, [load]);

  // Dwell time is an implicit-feedback signal, reported on unmount.
  useEffect(() => {
    enteredAt.current = Date.now();
    return () => {
      const seconds = Math.round((Date.now() - enteredAt.current) / 1000);
      if (id && seconds >= 3) track("time_spent", id, { seconds });
    };
  }, [id, track]);

  // Tab bar follows the section in view.
  useEffect(() => {
    if (!s) return;
    const els = TABS.map((t) => document.getElementById(t.id)).filter(Boolean) as HTMLElement[];
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveTab(visible[0].target.id);
      },
      { rootMargin: "-140px 0px -55% 0px" },
    );
    els.forEach((el) => obs.observe(el));
    // Near the top, the summary strip sits below the observer band; pin it.
    const onScroll = () => {
      if (window.scrollY < 160) setActiveTab("summary");
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      obs.disconnect();
      window.removeEventListener("scroll", onScroll);
    };
  }, [s, bench]);

  async function runEnrichment() {
    if (!id) return;
    if (s?.score) {
      setPrevScores({
        growth_potential: s.score.growth_potential_score,
        risk_level: s.score.risk_level_score,
        founder_credibility: s.score.founder_credibility_score,
        fraud_likelihood: s.score.fraud_likelihood_score,
      });
    }
    setEnriching(true);
    try {
      const res = await api.enrich(id, true);
      setTrace(res.trace);
      await load();
      toast({ title: "Verification agent finished", body: "Scores were recomputed from the new evidence.", tone: "good" });
    } catch (e) {
      setTrace({ error: String(e) });
      toast({ title: "Agent run failed", body: String(e), tone: "warning" });
    } finally {
      setEnriching(false);
    }
  }

  if (loading && !s)
    return (
      <div className="space-y-4">
        <div className="skeleton h-[220px]" />
        <div className="skeleton h-[110px]" />
        <div className="skeleton h-[420px]" />
      </div>
    );
  if (!s)
    return (
      <Card>
        {loadErr && !/404|not found/i.test(loadErr) ? (
          <SectionError message={loadErr} onRetry={() => void load()} />
        ) : (
          <Empty
            title="Startup not found"
            hint="It may have been removed, or the link is wrong."
            action={
              <Link to="/discover" className="btn">
                Back to Discover
              </Link>
            }
          />
        )}
      </Card>
    );

  const score = s.score;
  const band = scoreBand(score?.composite_score ?? null);
  const fraud = fraudBand(score?.fraud_likelihood_score ?? null);
  const fin = s.financials;
  // A corpus company never reported anything to us: it was imported from a
  // public dataset, and everything except its funding total is modelled.
  // A registration is the company's own submission, so it is described as such.
  const isSeeded = s.source.startsWith("seed");
  // Some corpus companies now carry the real founder names their source
  // dataset published; only the rest get the placeholder caption.
  const foundersAreModelled =
    s.founders.length > 0 && s.founders.every((f) => (f.name_source ?? "modelled") === "modelled");
  const attribution = score?.shap_top_features?.[activeDim];
  const gstGap =
    fin?.revenue && fin?.gst_reported_revenue
      ? Math.abs(fin.revenue - fin.gst_reported_revenue) / fin.revenue
      : null;

  return (
    <div className="animate-in space-y-5">
      {/* breadcrumb */}
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[13px] text-ink-muted">
        <Link to="/discover" className="font-medium text-brand-text hover:underline">
          Organizations
        </Link>
        <span aria-hidden>/</span>
        <Link to={`/discover?q=${encodeURIComponent(s.sector)}`} className="hover:text-ink">
          {s.sector}
        </Link>
        <span aria-hidden>/</span>
        <span className="truncate text-ink">{s.legal_name}</span>
      </nav>

      {/* ───────────────────────── profile header ───────────────────────── */}
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-5 p-5 sm:p-7 lg:flex-row lg:items-start">
          <LogoTile name={s.legal_name} src={s.logo_url} size={84} />
          <div className="min-w-0 flex-1 space-y-2.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[28px] font-extrabold leading-tight tracking-tight sm:text-[32px]">{s.legal_name}</h1>
              <VerifiedBadge verified={s.verified} />
              {s.status && <Badge tone="neutral">{titleCase(s.status)}</Badge>}
            </div>
            <p className="line-clamp-4 max-w-3xl text-[15px] leading-relaxed text-ink-secondary">
              {s.long_description ?? s.one_liner ?? "No description provided."}
            </p>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[13.5px] text-ink-secondary">
              {s.hq_city && (
                <span className="flex items-center gap-1.5">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path d="M12 21s7-6.2 7-12a7 7 0 10-14 0c0 5.8 7 12 7 12z" stroke="currentColor" strokeWidth="2" />
                    <circle cx="12" cy="9" r="2.5" stroke="currentColor" strokeWidth="2" />
                  </svg>
                  {s.hq_city}
                  {s.hq_state ? `, ${s.hq_state}` : ""}
                </span>
              )}
              <span>{stageLabel(s.stage)}</span>
              {s.founded_date ? <span>Founded {s.founded_date.slice(0, 4)}</span> : s.yc_batch ? <span>YC {s.yc_batch}</span> : null}
              {s.employee_count ? <span>{compactNum(s.employee_count)} employees</span> : null}
              {/* The company's own accounts, only where a real source published
                  them: the site itself, or the directory it came from. */}
              {s.company_linkedin_url && (
                <a href={s.company_linkedin_url} target="_blank" rel="noreferrer noopener"
                   className="font-semibold text-brand-text hover:underline">
                  LinkedIn ↗
                </a>
              )}
              {s.company_twitter_url && (
                <a href={s.company_twitter_url} target="_blank" rel="noreferrer noopener"
                   className="font-semibold text-brand-text hover:underline">
                  X ↗
                </a>
              )}
              {s.company_github_org && (
                <a href={`https://github.com/${s.company_github_org}`} target="_blank" rel="noreferrer noopener"
                   className="font-semibold text-brand-text hover:underline">
                  GitHub ↗
                </a>
              )}
              {s.website && (
                <a href={s.website} target="_blank" rel="noreferrer noopener" className="font-semibold text-brand-text hover:underline">
                  {s.website.replace(/^https?:\/\//, "").replace(/\/$/, "")} ↗
                </a>
              )}
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap gap-2 lg:flex-col lg:items-stretch">
            <button className="btn btn-primary h-11" onClick={runEnrichment} disabled={enriching}>
              {enriching ? "Running agent…" : "Run verification agent"}
            </button>
            <div className="flex gap-2">
              <button
                className="btn h-11 flex-1"
                onClick={() => void toggleSaved()}
                disabled={savePending}
                aria-pressed={saved}
              >
                {saved ? "★ Saved" : "☆ Save"}
              </button>
              <button
                className="btn h-11 flex-1"
                disabled={interested}
                onClick={() => {
                  track("save", s.startup_id);
                  track("interest_expressed", s.startup_id);
                  setInterested(true);
                  toast({ title: "Interest recorded", body: `${s.legal_name} was saved and will weigh on your feed.`, tone: "good" });
                }}
              >
                {interested ? "Interest recorded" : "Express interest"}
              </button>
              <button
                className="btn h-11"
                disabled={dismissed}
                onClick={() => {
                  track("dismiss", s.startup_id);
                  setDismissed(true);
                  toast({ title: "Dismissed", body: `Similar companies will rank lower in your feed.` });
                }}
              >
                {dismissed ? "Dismissed" : "Dismiss"}
              </button>
            </div>
          </div>
        </div>

        {/* tab bar — in-page sections */}
        <nav aria-label="Profile sections" className="flex gap-7 overflow-x-auto border-t border-line px-5 sm:px-7">
          {TABS.map((t) => (
            <a
              key={t.id}
              href={`#${t.id}`}
              aria-current={activeTab === t.id ? "true" : undefined}
              className="tab"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById(t.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
                setActiveTab(t.id);
              }}
            >
              {t.label}
              {activeTab === t.id && (
                <m.span
                  layoutId="profile-tab"
                  className="absolute inset-x-0 -bottom-px h-[2.5px] rounded-full bg-brand"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                />
              )}
            </a>
          ))}
        </nav>
      </Card>

      {/* ───────────────────────── highlights ───────────────────────── */}
      <Card id="summary" className="scroll-mt-24 overflow-hidden">
        {/* gap-px over a line-coloured ground draws dividers correctly at every
            breakpoint; the last tile widens so no empty cell shows through. */}
        <div className="grid grid-cols-2 gap-px bg-line md:grid-cols-3 xl:grid-cols-5 [&>*:last-child]:col-span-2 md:[&>*:last-child]:col-span-2 xl:[&>*:last-child]:col-span-1">
          <Highlight
            label="Composite score"
            value={score ? score.composite_score.toFixed(1) : "—"}
            tone={band.color}
            sub={
              score
                ? `${band.label} · ${score.confidence === "low" ? "low" : "high"} confidence (n=${score.cohort_size ?? "?"})`
                : "Not scored"
            }
          />
          <Highlight
            label="Total raised"
            value={compactUsd(fin?.total_funding_usd)}
            sub={
              bench?.percentiles?.total_funding_usd != null
                ? `${Math.round(bench.percentiles.total_funding_usd)}th pct. of peers`
                : "vs peers"
            }
          />
          <Highlight
            label="Revenue"
            value={compactUsd(fin?.revenue)}
            sub={
              fin?.revenue_growth_pct != null ? (
                <span className={fin.revenue_growth_pct >= 0 ? "text-good" : "text-serious"}>
                  {fin.revenue_growth_pct >= 0 ? "↑" : "↓"} {Math.abs(fin.revenue_growth_pct).toFixed(0)}% year on year
                </span>
              ) : (
                "Growth not reported"
              )
            }
          />
          <Highlight
            label="Runway"
            value={fin?.runway_months ? `${fin.runway_months.toFixed(0)} mo` : "—"}
            tone={fin?.runway_months && fin.runway_months < 12 ? "var(--color-warning)" : undefined}
            sub={fin?.burn_rate_monthly ? `${compactUsd(fin.burn_rate_monthly)} monthly burn` : "Burn not reported"}
          />
          <Highlight
            label="Fraud likelihood"
            value={score ? String(Math.round(score.fraud_likelihood_score)) : "—"}
            tone={fraud.color}
            sub={`Lower is better · ${fraud.label.toLowerCase()}`}
          />
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        {/* ─────────────────────── left column ─────────────────────── */}
        <div className="min-w-0 space-y-5">
          {score && (
            <Card id="scores" className="scroll-mt-24 p-5 sm:p-6">
              <SectionHeader
                title="Four independent scores"
                description="Computed separately, not as one fused model — combining these too early measurably degrades accuracy. Select one to see what drove it."
              />
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {DIMENSIONS.map((d) => {
                  const val = score[d.scoreKey] as number;
                  const isFraud = d.key === "fraud_likelihood";
                  const active = activeDim === d.key;
                  const prev = prevScores?.[d.key];
                  const changed = prev !== undefined && Math.abs(prev - val) >= 0.1;
                  return (
                    <button
                      key={d.key}
                      onClick={() => setActiveDim(d.key)}
                      aria-pressed={active}
                      className={`relative flex flex-col items-center gap-1.5 rounded-xl border p-4 transition-colors ${
                        active ? "border-brand bg-brand-tint" : "border-line bg-surface hover:bg-raised"
                      }`}
                    >
                      {changed && (
                        <span
                          className="tnum absolute right-2 top-2 text-[11px] font-bold"
                          style={{
                            color:
                              (val > prev!) === !isFraud ? "var(--color-good)" : "var(--color-serious)",
                          }}
                          title="Change since the verification agent last ran"
                        >
                          {val > prev! ? "↑" : "↓"}
                          {Math.abs(val - prev!).toFixed(0)}
                        </span>
                      )}
                      <ScoreRing value={val} size={70} invert={isFraud} />
                      <span className={`text-center text-[13px] font-bold ${active ? "text-brand-text" : "text-ink"}`}>
                        {d.label}
                      </span>
                      <span className="text-[11px] text-ink-muted">
                        {isFraud ? "higher = worse" : methodBadge(score.shap_top_features?.[d.key]?.method)}
                      </span>
                    </button>
                  );
                })}
              </div>

              <div className="mt-5 grid gap-6 border-t border-line pt-5 lg:grid-cols-2">
                <div>
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className="eyebrow">Top contributing features</span>
                    {attribution?.method && (
                      <span className="chip text-[11px]" title={methodTitle(attribution.method)}>
                        {methodLabel(attribution.method)}
                      </span>
                    )}
                  </div>
                  {attribution?.features?.length ? (
                    <AttributionBars items={attribution.features} />
                  ) : (
                    <p className="text-[13px] text-ink-muted">No attributions recorded for this dimension.</p>
                  )}
                </div>
                <div>
                  <div className="eyebrow mb-3">In plain English</div>
                  <p className="text-[14px] leading-relaxed text-ink-secondary">{score.rationale?.[activeDim] ?? "—"}</p>
                  <div className="mt-4 rounded-xl bg-plane p-3.5">
                    <div className="eyebrow mb-1.5">Composite</div>
                    <p className="text-[13px] leading-relaxed text-ink-secondary">{score.rationale?.composite}</p>
                    <p className="tnum mt-2 text-[11.5px] text-ink-muted">
                      {score.model_version} · scored {relativeTime(score.computed_at)}
                    </p>
                  </div>
                </div>
              </div>
            </Card>
          )}

          <MentorsPanel startupId={s.startup_id} ownerIsMe={!!s.owned_by_me} />

          <Card id="financials" className="scroll-mt-24 p-5 sm:p-6">
            <SectionHeader
              title="Financials"
              description={
                isSeeded
                  ? "Modelled from public funding records — this company never reported to us. Only the funding total is observed."
                  : "As reported by the company, cross-checked where a source exists."
              }
            />
            {fin ? (
              <>
                <div className="grid grid-cols-2 gap-x-6 border-y border-line sm:grid-cols-4">
                  <Metric label="Revenue" value={compactUsd(fin.revenue)} />
                  <Metric
                    label="YoY growth"
                    value={fin.revenue_growth_pct != null ? `${fin.revenue_growth_pct.toFixed(0)}%` : "—"}
                    tone={(fin.revenue_growth_pct ?? 0) > 0 ? "var(--color-good)" : undefined}
                  />
                  <Metric label="Monthly burn" value={compactUsd(fin.burn_rate_monthly)} />
                  <Metric
                    label="Runway"
                    value={fin.runway_months ? `${fin.runway_months.toFixed(0)} mo` : "—"}
                    tone={fin.runway_months && fin.runway_months < 12 ? "var(--color-warning)" : undefined}
                    hint={fin.runway_months && fin.runway_months < 12 ? "below 12 months" : undefined}
                  />
                  <Metric label="Cash balance" value={compactUsd(fin.cash_balance)} />
                  <Metric
                    label="LTV : CAC"
                    value={fin.ltv_cac_ratio ? `${fin.ltv_cac_ratio.toFixed(1)}x` : "—"}
                    tone={fin.ltv_cac_ratio && fin.ltv_cac_ratio >= 3 ? "var(--color-good)" : undefined}
                    hint="3.0x benchmark"
                  />
                  <Metric label="TAM" value={compactUsd(fin.tam_usd)} />
                  <Metric label="Total raised" value={compactUsd(fin.total_funding_usd)} />
                </div>

                {gstGap !== null && (
                  <div
                    className={`mt-4 flex gap-3 rounded-xl border p-4 ${
                      gstGap > 0.2 ? "border-critical-line bg-critical-tint" : "border-good-line bg-good-tint"
                    }`}
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden className="mt-px shrink-0" style={{ color: gstGap > 0.2 ? "var(--color-critical)" : "var(--color-good)" }}>
                      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
                      {gstGap > 0.2 ? (
                        <path d="M12 7.5v5.5M12 16.5h.01" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
                      ) : (
                        <path d="M8.5 12l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                      )}
                    </svg>
                    <div className="text-[13.5px] leading-relaxed" style={{ color: gstGap > 0.2 ? "var(--color-critical-text)" : "var(--color-good-text)" }}>
                      <div className="flex flex-wrap items-center gap-2">
                        <b>{gstGap > 0.2 ? "Revenue mismatch" : "Revenue within tolerance"}</b>
                        {/* The GST register lookup can be live, but turnover is never public:
                            the figure compared here is always simulated. */}
                        <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-ink-secondary">
                          <ProvenanceDot isMock />
                          GST turnover (simulated)
                        </span>
                      </div>
                      Founder reports <b className="tnum">{compactUsd(fin.revenue)}</b>; the simulated GST figure is{" "}
                      <b className="tnum">{compactUsd(fin.gst_reported_revenue)}</b> — a{" "}
                      <b className="tnum">{(gstGap * 100).toFixed(0)}%</b> gap
                      {gstGap > 0.2 ? ", above the 20% threshold that triggers a fraud flag." : ", within the 20% tolerance."}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <Empty title="No financials on record" hint="Idea-stage companies are not asked for financial metrics." />
            )}
          </Card>

          <Card id="signals" className="scroll-mt-24 p-5 sm:p-6">
            <SectionHeader
              title="Fraud & risk signals"
              description="Unsupervised detectors plus cross-source rules. Nothing here is an automated rejection — flagged profiles go to human review."
            />
            {s.fraud_signals.length ? (
              <div className="space-y-2.5">
                {s.fraud_signals.map((sig) => (
                  <div key={sig.signal_id} className="rounded-xl border border-line bg-plane p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-bold">{titleCase(sig.detector)}</span>
                      <Badge tone={SEVERITY_BADGE[sig.severity] ?? "warning"}>{sig.severity}</Badge>
                      <Badge tone={sig.reviewed_by_human ? "good" : "neutral"}>
                        {sig.reviewed_by_human ? "Reviewed" : "Pending review"}
                      </Badge>
                      <span className="tnum ml-auto text-[12px] text-ink-muted">score {sig.anomaly_score.toFixed(2)}</span>
                    </div>
                    <p className="mt-2 text-[13.5px] leading-relaxed text-ink-secondary">{sig.explanation}</p>
                    {sig.flagged_fields?.length ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {sig.flagged_fields.map((f) => (
                          <span key={f} className="chip bg-surface text-[11px]">
                            {f}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <Empty tone="good" title="All consistency checks passed" hint="No detector or rule raised a signal for this company." />
            )}
          </Card>
        </div>

        {/* ─────────────────────── right column ─────────────────────── */}
        <div className="min-w-0 space-y-5">
          <Card className="p-5 sm:p-6">
            <SectionHeader title="About" />
            <div>
              <KV k="Industry">{s.sector}</KV>
              {s.sub_vertical && <KV k="Focus">{s.sub_vertical}</KV>}
              <KV k="Stage">{stageLabel(s.stage)}</KV>
              <KV k="Headquarters">{[s.hq_city, s.hq_state].filter(Boolean).join(", ") || "—"}</KV>
              <KV k="Founded">{s.founded_date?.slice(0, 4) ?? "—"}</KV>
              {s.yc_batch && <KV k="Y Combinator batch">{s.yc_batch}</KV>}
              <KV k="CIN">{s.cin ? <span className="tnum text-[12.5px]">{s.cin}</span> : "Not on record"}</KV>
              <KV k="Peer cohort">{score?.cohort_size ? `${score.cohort_size} companies` : "—"}</KV>
              <KV k="Record source">{SOURCE_LABEL[s.source] ?? s.source.replace(/_/g, " ")}</KV>
            </div>
          </Card>

          <Card id="people" className="scroll-mt-24 p-5 sm:p-6">
            <SectionHeader
              title={`Founders (${s.founders.length})`}
              description={
                foundersAreModelled
                  ? "We did not collect who founded this company. The profiles below are modelled, not real people."
                  : isSeeded
                    ? "Names from the public funding records this company was imported from. The credibility signals beside them are modelled."
                    : undefined
              }
            />
            {s.founders.length ? (
              <div className="space-y-4">
                {s.founders.map((f) => (
                  <div key={f.founder_id} className="flex gap-3">
                    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-brand-tint text-[14px] font-bold text-brand-text">
                      {f.name
                        .split(" ")
                        .map((p) => p[0])
                        .slice(0, 2)
                        .join("")}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[14.5px] font-bold">{f.name}</span>
                        <span className="text-[12.5px] text-ink-muted">{f.role}</span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {f.prior_exits ? (
                          <Badge tone="good">
                            {f.prior_exits} prior exit{f.prior_exits > 1 ? "s" : ""}
                          </Badge>
                        ) : null}
                        {f.domain_experience_years != null && (
                          <span className="chip">{f.domain_experience_years.toFixed(0)}y domain</span>
                        )}
                        {f.github_commit_count_90d ? <span className="chip">{compactNum(f.github_commit_count_90d)} commits</span> : null}
                        {f.github_followers ? <span className="chip">{compactNum(f.github_followers)} followers</span> : null}
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-3 text-[12.5px]">
                        {f.linkedin_url && (
                          <a href={f.linkedin_url} target="_blank" rel="noreferrer noopener" className="font-semibold text-brand-text hover:underline">
                            LinkedIn ↗
                          </a>
                        )}
                        {f.github_username && (
                          <a
                            href={`https://github.com/${f.github_username}`}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="font-semibold text-brand-text hover:underline"
                          >
                            GitHub ↗
                          </a>
                        )}
                        {!f.linkedin_url && !f.github_username && (
                          <span className="text-ink-muted">
                            {isSeeded ? "No public profile collected" : "No verifiable public profile"}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty title="No founder profiles" hint="Run the verification agent to attach and enrich founder records." />
            )}
          </Card>

          <Card id="provenance" className="scroll-mt-24 p-5 sm:p-6">
            <SectionHeader
              title="Source provenance"
              description="Which sources were queried, and whether each is live or a mocked stand-in."
            />

            {trace && (
              <div className="mb-4 panel rounded-xl p-4 text-[13px]">
                <div className="mb-2 flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-panel-accent" />
                  <span className="font-bold text-panel-ink">Agent trace</span>
                  <button className="ml-auto text-[12px] text-panel-muted hover:text-panel-ink" onClick={() => setTrace(null)}>
                    Dismiss
                  </button>
                </div>
                {trace.error ? (
                  <p className="text-[#ffb4b4]">{trace.error}</p>
                ) : (
                  <>
                    <p className="tnum text-[12px] text-panel-muted">
                      plan → {trace.planned?.join(" → ") || "nothing (all cached)"}
                    </p>
                    {trace.escalations?.map((e: any, i: number) => (
                      <p key={i} className="mt-1.5 text-panel-warn">
                        ⚠ {e.detail} → {e.action}
                      </p>
                    ))}
                  </>
                )}
              </div>
            )}

            {enriching && <Spinner label="Agent querying sources…" />}

            {s.enrichments.length ? (
              <div className="space-y-2">
                {s.enrichments.map((e) => (
                  <div key={e.enrichment_id} className="flex min-w-0 items-center gap-2.5 rounded-lg bg-plane px-3 py-2.5">
                    <ProvenanceDot isMock={e.is_mock} />
                    <span className="w-[104px] shrink-0 text-[13px] font-bold">{ENRICH_LABEL[e.source] ?? e.source}</span>
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-muted">
                      {e.raw_response?.summary ?? (e.is_mock ? (e.raw_response?._why_mock ?? "mocked source") : "live API call")}
                    </span>
                    <Badge tone={e.status === "success" ? "good" : "critical"}>{e.status}</Badge>
                  </div>
                ))}
              </div>
            ) : (
              <Empty title="No enrichment yet" hint="Run the verification agent to cross-check this profile." />
            )}
          </Card>

          <DocumentUpload startupId={s.startup_id} compact />
        </div>
      </div>

      {/* ───────────────────────── peers ───────────────────────── */}
      <div id="peers" className="scroll-mt-24 space-y-5">
        <Competitors startupId={s.startup_id} />
        {benchErr && (
          <Card className="p-5">
            <SectionHeader title="Peer comparison" />
            <SectionError message={benchErr} onRetry={() => void load()} />
          </Card>
        )}
        {bench && (
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-4 sm:px-6">
              <div className="min-w-0 flex-1">
                <h2 className="text-[17px] font-bold">Peer comparison</h2>
                <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-ink-muted">{bench.narrative}</p>
              </div>
              <Badge tone={bench.confidence === "high" ? "good" : "warning"}>{bench.confidence} confidence</Badge>
            </div>
            {bench.peers.length ? (
              <div className="overflow-x-auto">
                <table className="data-table min-w-[600px]">
                  <thead>
                    <tr>
                      <th className="col-sticky text-left">Peer</th>
                      <th className="text-left">Stage</th>
                      <th className="text-right">Similarity</th>
                      <th className="text-right">Score</th>
                      <th className="text-right">Raised</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bench.peers.map((p) => (
                      <tr key={p.startup_id}>
                        <td className="col-sticky">
                          <Link to={`/startup/${p.startup_id}`} className="flex items-center gap-2.5">
                            <LogoTile name={p.legal_name} size={26} />
                            <span className="font-bold text-brand-text hover:underline">{p.legal_name}</span>
                          </Link>
                        </td>
                        <td className="whitespace-nowrap text-ink-secondary">{stageLabel(p.stage)}</td>
                        <td className="tnum text-right text-ink-secondary">{(p.similarity * 100).toFixed(1)}%</td>
                        <td className="tnum text-right font-semibold" style={{ color: scoreBand(p.composite_score).color }}>
                          {p.composite_score?.toFixed(0) ?? "—"}
                        </td>
                        <td className="tnum whitespace-nowrap text-right text-ink-secondary">{compactUsd(p.total_funding_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty title="No comparable peers found" />
            )}
          </Card>
        )}

        {similarErr && (
          <Card className="p-5">
            <SectionHeader title="Similar companies" />
            <SectionError message={similarErr} onRetry={() => void load()} />
          </Card>
        )}
        {similar.length > 0 && (
          <div>
            <h2 className="mb-3 text-[17px] font-bold">Similar companies</h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {similar.map((p) => (
                <Link key={p.startup_id} to={`/startup/${p.startup_id}`} className="card card-lit interactive flex flex-col gap-2 p-4">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <LogoTile name={p.legal_name} size={32} />
                    <span className="min-w-0 flex-1 truncate text-[14px] font-bold">{p.legal_name}</span>
                    <span className="tnum text-[15px] font-semibold" style={{ color: scoreBand(p.composite_score).color }}>
                      {p.composite_score?.toFixed(0) ?? "—"}
                    </span>
                  </div>
                  <p className="line-clamp-2 text-[12.5px] leading-relaxed text-ink-muted">{p.one_liner ?? p.sector}</p>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
