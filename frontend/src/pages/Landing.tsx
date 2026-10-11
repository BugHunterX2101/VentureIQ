import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { m, useReducedMotion, useScroll, useTransform, type Variants } from "motion/react";
import {
  api,
  type Alert,
  type ConstellationData,
  type EnrichmentRecord,
  type Match,
  type PlatformStats,
  type StartupDetail,
  type StartupSummary,
} from "../lib/api";
import { apiDate, compactUsd, fraudBand, scoreBand, stageLabel } from "../lib/format";
import { useTheme } from "../lib/theme";
import { Logo } from "../components/Shell";
import { LogoTile } from "../components/primitives";
import { useInvestor } from "../lib/investor-context";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { NumberTicker, Sheen, Spotlight, Tilt, useInView } from "../components/ui/effects";
import { PALETTE_3D, fraudColor } from "../components/three/palette3d";

// three.js only downloads once a scene is about to be seen.
const Constellation = lazy(() => import("../components/three/Constellation"));
const ScoreTowers = lazy(() => import("../components/three/ScoreTowers"));
const AgentGraph = lazy(() => import("../components/three/AgentGraph"));

/* ───────────────────────────── motion presets ───────────────────────────── */

const EASE = [0.16, 1, 0.3, 1] as const;

const rise: Variants = {
  hidden: { opacity: 0, y: 22 },
  show: (i: number = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, delay: i * 0.08, ease: EASE },
  }),
};

function Reveal({ children, className = "", i = 0 }: { children: ReactNode; className?: string; i?: number }) {
  return (
    <m.div
      className={className}
      variants={rise}
      custom={i}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-80px" }}
    >
      {children}
    </m.div>
  );
}

/** Headline that assembles word by word. */
function StaggerWords({ text, className = "", delay = 0 }: { text: string; className?: string; delay?: number }) {
  return (
    <>
      {text.split(" ").map((w, i) => (
        <m.span
          key={i}
          className={`inline-block ${className}`}
          initial={{ opacity: 0, y: "0.45em", filter: "blur(6px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ duration: 0.6, delay: delay + i * 0.05, ease: EASE }}
        >
          {w}&nbsp;
        </m.span>
      ))}
    </>
  );
}

/** Mounts children only once the placeholder is near the viewport. */
function WhenNear({ children, className }: { children: ReactNode; className: string }) {
  const [ref, seen] = useInView<HTMLDivElement>("300px");
  return (
    <div ref={ref} className={className}>
      {seen ? <Suspense fallback={<SceneLoading />}>{children}</Suspense> : <SceneLoading />}
    </div>
  );
}

function SceneLoading() {
  return <div className="skeleton h-full w-full rounded-2xl opacity-40" />;
}

const fmt = (n: number | null | undefined, d = 0) =>
  n === null || n === undefined ? "—" : n.toLocaleString("en-US", { maximumFractionDigits: d });

const SOURCE_NAME: Record<string, string> = {
  mca21: "MCA21",
  gstn: "GSTN",
  github: "GitHub",
  linkedin: "LinkedIn",
  whois: "WHOIS",
};

/** Latest record per source, in the order the agent ran them. */
function latestPerSource(records: EnrichmentRecord[]) {
  const by = new Map<string, EnrichmentRecord>();
  for (const r of records) {
    const prev = by.get(r.source);
    if (!prev || r.retrieved_at > prev.retrieved_at) by.set(r.source, r);
  }
  return [...by.values()].sort((a, b) => a.retrieved_at.localeCompare(b.retrieved_at));
}

/* ───────────────────────────── small pieces ─────────────────────────────── */

function Arrow() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Tick() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden className="shrink-0 text-brand-text">
      <path d="M5 12l4.5 4.5L19 7" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Kicker({ children, onPanel }: { children: ReactNode; onPanel?: boolean }) {
  return (
    <div className={`text-[13px] font-bold tracking-[0.1em] ${onPanel ? "text-panel-muted" : "text-brand-text"}`}>
      {children}
    </div>
  );
}

function Phone({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`w-[250px] rounded-[42px] bg-panel p-[9px] shadow-[var(--shadow-float)] ring-1 ring-line-strong ${className}`}>
      <div className="relative h-[510px] overflow-hidden rounded-[34px] bg-plane">
        <div className="absolute left-1/2 top-[9px] z-10 h-[22px] w-[76px] -translate-x-1/2 rounded-full bg-panel" />
        {children}
      </div>
    </div>
  );
}

function MiniScore({ label, value, invert }: { label: string; value: number | null; invert?: boolean }) {
  const color = invert ? fraudBand(value).color : scoreBand(value).color;
  return (
    <div className="rounded-[10px] border border-line bg-surface px-2.5 py-2">
      <div className="text-[9.5px] font-medium text-ink-muted">{label}</div>
      <div className="tnum text-[17px] font-semibold" style={{ color }}>
        {value === null ? "—" : Math.round(value)}
      </div>
    </div>
  );
}

function LegendDot({ color, label, pulse }: { color: string; label: string; pulse?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${pulse ? "pulse-ring" : ""}`} style={{ background: color }} />
      {label}
    </span>
  );
}

/* ───────────────────────────────── page ─────────────────────────────────── */

export default function Landing() {
  const reduce = useReducedMotion();
  const navigate = useNavigate();
  const { theme } = useTheme();
  const { current } = useInvestor();

  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [metrics, setMetrics] = useState<any>(null);
  const [top, setTop] = useState<StartupSummary[]>([]);
  const [lead, setLead] = useState<StartupDetail | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [sky, setSky] = useState<ConstellationData | null>(null);
  const [skyError, setSkyError] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    // The latency figure is measured here, live. The search runs FIRST and
    // alone — the API is single-worker, so firing it alongside other requests
    // would measure queueing, not search.
    const t0 = performance.now();
    api
      .startups({ limit: 7, sort: "composite_score", verified_only: true })
      .then((r) => {
        setLatency(Math.round(performance.now() - t0));
        setTop(r.items);
        if (r.items[0]) api.startup(r.items[0].startup_id).then(setLead).catch(() => {});
      })
      .catch(() => {})
      .finally(() => {
        api.constellation().then(setSky).catch(() => setSkyError(true));
        api.stats().then(setStats).catch(() => {});
        api.modelMetrics().then(setMetrics).catch(() => {});
        // Enough history to still find alerts after scoping to the mandate.
        api.alerts(100).then(setAlerts).catch(() => {});
      });

    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!current) return;
    api.feed(current.investor_id, { limit: 4 }).then(setMatches).catch(() => {});
  }, [current]);

  // The product render flattens as it scrolls through — a Framer-style parallax.
  const productRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: productRef, offset: ["start end", "center center"] });
  const rotateX = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [14, 0]);
  const scale = useTransform(scrollYProgress, [0, 1], reduce ? [1, 1] : [0.94, 1]);
  const phoneY = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [80, 0]);

  const auroc = metrics?.comparison?.[metrics?.chosen_model]?.auroc as number | undefined;
  const mandateAlerts = (() => {
    const mine = current?.preference?.preferred_sectors ?? [];
    const list = mine.length ? alerts.filter((a) => mine.includes(a.sector)) : alerts;
    return list.slice(0, 2);
  })();

  const leadScore = lead?.score;
  const gst =
    lead?.financials?.revenue && lead.financials.gst_reported_revenue
      ? Math.abs(lead.financials.revenue - lead.financials.gst_reported_revenue) / lead.financials.revenue
      : null;

  const trace = useMemo(() => latestPerSource(lead?.enrichments ?? []), [lead]);
  const steps = useMemo(
    () => trace.map((r) => ({ source: SOURCE_NAME[r.source] ?? r.source, live: !r.is_mock, status: r.status })),
    [trace],
  );

  const towers = leadScore
    ? [
        { label: "Growth", value: leadScore.growth_potential_score },
        { label: "Safety", value: leadScore.risk_level_score },
        { label: "Founder", value: leadScore.founder_credibility_score },
        { label: "Fraud ↓", value: leadScore.fraud_likelihood_score, invert: true },
      ]
    : null;

  // Real fraud-score histogram from the same sample the hero draws.
  const fraudHist = useMemo(() => {
    if (!sky) return null;
    const bins = Array.from({ length: 10 }, () => 0);
    sky.fraud.forEach((f) => bins[Math.min(9, Math.floor(f / 10))]++);
    return bins;
  }, [sky]);
  const flaggedInSample = sky ? sky.fraud.filter((f) => f >= 35).length : null;

  const scene = PALETTE_3D[theme];
  const panelScene = PALETTE_3D.dark; // panels are navy in both themes

  return (
    <div className="min-h-screen overflow-x-clip bg-plane text-ink">
      {/* ─────────────────────────────── nav ─────────────────────────────── */}
      <header
        className={`sticky top-0 z-50 transition-[background-color,border-color] duration-200 ${
          scrolled ? "border-b border-line bg-header backdrop-blur-md" : "border-b border-transparent"
        }`}
      >
        <div className="mx-auto flex h-[72px] max-w-[1320px] items-center gap-10 px-5 sm:px-8">
          <Logo />
          <nav className="hidden items-center gap-7 text-[14.5px] font-medium text-ink-secondary md:flex">
            {[
              ["#product", "Product"],
              ["#how", "How it works"],
              ["#mobile", "Mobile"],
              ["#model", "Model"],
            ].map(([href, label]) => (
              <a key={href} href={href} className="group relative transition-colors hover:text-ink">
                {label}
                <span className="absolute -bottom-1 left-0 h-0.5 w-full origin-left scale-x-0 rounded-full bg-brand transition-transform duration-300 group-hover:scale-x-100" />
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2.5 sm:gap-3">
            <Link to="/discover" className="hidden text-[14.5px] font-semibold text-ink-secondary hover:text-ink lg:block">
              Browse companies
            </Link>
            <ThemeToggle />
            <Sheen className="rounded-[10px]">
              <Link to="/dashboard" className="btn btn-primary px-4 sm:px-5">
                Open the platform
              </Link>
            </Sheen>
          </div>
        </div>
      </header>

      {/* ─────────────────────────────── hero ────────────────────────────── */}
      <section className="relative">
        <div aria-hidden className="dot-grid pointer-events-none absolute inset-0 -top-[72px] [mask-image:radial-gradient(ellipse_at_70%_30%,#000_20%,transparent_70%)]" />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -top-[72px]"
          style={{
            background:
              "radial-gradient(900px 560px at 76% 34%, var(--color-hero-glow) 0%, transparent 70%)",
          }}
        />
        <div className="relative mx-auto grid max-w-[1320px] items-center gap-10 px-5 pb-16 pt-10 sm:px-8 lg:grid-cols-[minmax(0,500px)_minmax(0,1fr)] lg:pb-20 lg:pt-12">
          <div className="flex flex-col gap-6">
            <m.div variants={rise} initial="hidden" animate="show" custom={0}>
              <span className="inline-flex items-center gap-2 rounded-full border border-brand-dim bg-surface py-1.5 pl-2 pr-3.5 text-[13px] font-semibold text-brand-text shadow-[var(--shadow-card)]">
                <span className="pulse-ring h-2 w-2 rounded-full bg-brand" />
                {stats ? `${fmt(stats.scored)} startups scored and cross-checked` : "Loading live platform data…"}
              </span>
            </m.div>
            <h1 className="text-[42px] font-extrabold leading-[1.04] tracking-[-0.035em] sm:text-[56px] lg:text-[60px]">
              <StaggerWords text="Private-market intelligence you can" delay={0.08} />
              <StaggerWords text="actually verify." className="text-brand-text" delay={0.35} />
            </h1>
            <m.p variants={rise} initial="hidden" animate="show" custom={4} className="text-[17px] leading-relaxed text-ink-secondary sm:text-[18.5px]">
              VentureIQ checks what founders claim against independent sources, scores every startup on
              four explainable dimensions, and flags the numbers that don't reconcile — before you write
              the cheque.
            </m.p>
            <m.div variants={rise} initial="hidden" animate="show" custom={5} className="flex flex-wrap gap-3">
              <Sheen className="rounded-xl">
                <Link to="/dashboard" className="btn btn-primary h-12 rounded-xl px-6 text-[15.5px]">
                  Explore the platform <Arrow />
                </Link>
              </Sheen>
              {top[0] && (
                <Link to={`/startup/${top[0].startup_id}`} className="btn h-12 rounded-xl px-5 text-[15.5px]">
                  See a company profile
                </Link>
              )}
            </m.div>
            <m.div variants={rise} initial="hidden" animate="show" custom={6} className="flex flex-wrap gap-x-7 gap-y-4 pt-3">
              <div>
                <NumberTicker value={auroc} format={(n) => n.toFixed(3)} className="tnum block text-[26px] font-semibold" />
                <div className="text-[12.5px] text-ink-muted">held-out AUROC</div>
              </div>
              <div className="w-px bg-line-strong" />
              <div>
                <NumberTicker value={stats?.verified} className="tnum block text-[26px] font-semibold" />
                <div className="text-[12.5px] text-ink-muted">registry-verified</div>
              </div>
              <div className="w-px bg-line-strong" />
              <div>
                <div className="tnum text-[26px] font-semibold">{latency ? `${latency}ms` : "—"}</div>
                <div className="text-[12.5px] text-ink-muted">search, measured just now</div>
              </div>
            </m.div>
          </div>

          {/* live constellation */}
          <m.figure
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 1, delay: 0.15, ease: EASE }}
            className="relative m-0"
          >
            <div className="relative h-[380px] sm:h-[500px] lg:h-[560px]">
              {sky ? (
                <Suspense fallback={<SceneLoading />}>
                  <Constellation
                    data={sky}
                    theme={theme}
                    onOpen={(id) => navigate(`/startup/${id}`)}
                    className="h-full w-full"
                  />
                </Suspense>
              ) : skyError ? (
                <div className="grid h-full place-items-center text-[14px] text-ink-muted">
                  The live company map couldn't load. Is the API running?
                </div>
              ) : (
                <SceneLoading />
              )}
            </div>
            <figcaption className="mt-2 flex flex-col gap-2.5 text-[12.5px] text-ink-muted sm:flex-row sm:items-end sm:justify-between">
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-ink-secondary">
                <LegendDot color={scene.strong} label="Composite ≥ 75" />
                <LegendDot color={scene.moderate} label="55–75" />
                <LegendDot color={scene.weak} label="35–55" />
                <LegendDot color={scene.flagged} label="Fraud ≥ 35" pulse />
              </div>
              <div className="max-w-[330px] leading-snug sm:text-right">
                {sky
                  ? `${fmt(sky.count)} of ${fmt(stats?.startups)} real companies, one arm per sector. Nearer the core scores higher. Hover a point, click to open it.`
                  : "Loading the company map…"}
              </div>
            </figcaption>
          </m.figure>
        </div>
      </section>

      {/* ───────────────────────────── sources ───────────────────────────── */}
      <section className="border-y border-line bg-surface py-6">
        <div className="mx-auto flex max-w-[1320px] items-center gap-8 px-5 sm:px-8">
          <div className="hidden w-40 shrink-0 text-[13px] font-semibold text-ink-muted md:block">Evidence drawn from</div>
          <div className="marquee-wrap relative flex-1 overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)]">
            <div className="marquee flex w-max gap-14 whitespace-nowrap text-[17px] font-bold tracking-tight text-ink-muted">
              {[0, 1].map((k) => (
                <div key={k} className="flex gap-14" aria-hidden={k === 1}>
                  <span>MCA company master data</span>
                  <span>GST taxpayer register</span>
                  <span>Company websites</span>
                  <span>Domain registry (RDAP)</span>
                  <span>GitHub</span>
                  <span>Founder LinkedIn profiles</span>
                  <span>Y Combinator directory</span>
                  <span>Indian funding records</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ───────────────────────────── live stats ────────────────────────── */}
      <section className="mx-auto grid max-w-[1320px] gap-4 px-5 py-16 sm:grid-cols-2 sm:px-8 lg:grid-cols-4 lg:py-20">
        {[
          { v: stats?.startups, l: "Startups indexed", d: "Every one scored on four independent dimensions." },
          { v: stats?.total_tracked_funding_usd, f: (n: number) => compactUsd(n), l: "Capital tracked", d: "Across all recorded funding rounds." },
          { v: stats?.flagged_startups, l: "Flagged for review", d: "Anomaly and cross-source rules. Humans decide.", warm: true },
          { v: stats?.enrichment_calls, l: "Enrichment records", d: "Each marked live or mocked — never blurred." },
        ].map((s, i) => (
          <Reveal key={s.l} i={i}>
            <Spotlight
              className="card card-lit interactive h-full p-6"
              color={s.warm ? "var(--color-serious)" : "var(--color-brand)"}
            >
              <NumberTicker
                value={s.v}
                format={s.f}
                className={`tnum block text-[38px] font-semibold tracking-tight ${s.warm ? "text-serious" : ""}`}
              />
              <div className="mt-1.5 text-[15px] font-bold">{s.l}</div>
              <div className="mt-1 text-[13.5px] leading-relaxed text-ink-muted">{s.d}</div>
            </Spotlight>
          </Reveal>
        ))}
      </section>

      {/* ───────────────────────────── product render ────────────────────── */}
      <section ref={productRef} className="mx-auto max-w-[1180px] px-5 pb-20 sm:px-8 [perspective:1600px]">
        <m.div style={{ rotateX, scale, transformOrigin: "center top" }} className="relative">
          <Tilt max={3}>
            <div className="beam relative overflow-hidden rounded-2xl border border-line-strong bg-surface shadow-[var(--shadow-float)]">
              <div className="flex h-9 items-center gap-1.5 border-b border-line bg-raised px-3.5">
                <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
                <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
                <div className="ml-4 flex h-[22px] flex-1 items-center rounded-md border border-line bg-surface px-2.5 text-[11px] text-ink-muted">
                  ventureiq / discover
                </div>
              </div>
              <div className="flex">
                <div className="hidden w-14 flex-col items-center gap-4 bg-panel pt-4 sm:flex">
                  <div className="h-7 w-7 rounded-[7px] bg-brand" />
                  <div className="h-5 w-5 rounded-[5px] bg-panel-line" />
                  <div className="h-5 w-5 rounded-[5px] bg-panel-raised" />
                  <div className="h-5 w-5 rounded-[5px] bg-panel-raised" />
                </div>
                <div className="min-w-0 flex-1 space-y-3 p-4 sm:p-5">
                  <div className="relative flex h-9 items-center overflow-hidden rounded-lg border border-line-strong px-3 text-[12.5px] text-ink-muted">
                    Search companies, sectors, founders…
                    <div className="scan absolute inset-y-0 w-20 bg-gradient-to-r from-transparent via-brand-tint to-transparent opacity-80" />
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <span className="chip chip-brand">Verified only</span>
                    <span className="chip chip-brand">Sorted by composite</span>
                  </div>
                  <div className="overflow-hidden rounded-[10px] border border-line">
                    <div className="grid grid-cols-[minmax(0,2.2fr)_repeat(3,minmax(0,1fr))] border-b border-line bg-table-head px-3 py-2 text-[10px] font-bold tracking-[0.06em] text-ink-muted sm:grid-cols-[minmax(0,2.2fr)_repeat(4,minmax(0,1fr))]">
                      <span>ORGANIZATION</span>
                      <span className="text-right">SCORE</span>
                      <span className="text-right">GROWTH</span>
                      <span className="hidden text-right sm:block">FRAUD</span>
                      <span className="text-right">RAISED</span>
                    </div>
                    {(top.length ? top : Array.from({ length: 7 }).map(() => null)).map((s, i) => (
                      <m.div
                        key={s?.startup_id ?? i}
                        initial={{ opacity: 0, x: -8 }}
                        whileInView={{ opacity: 1, x: 0 }}
                        viewport={{ once: true }}
                        transition={{ delay: 0.15 + i * 0.06 }}
                        className="grid grid-cols-[minmax(0,2.2fr)_repeat(3,minmax(0,1fr))] items-center border-b border-grid px-3 py-2 text-[12px] transition-colors last:border-0 hover:bg-row-hover sm:grid-cols-[minmax(0,2.2fr)_repeat(4,minmax(0,1fr))]"
                      >
                        {s ? (
                          <>
                            <Link to={`/startup/${s.startup_id}`} className="flex min-w-0 items-center gap-2 font-semibold hover:text-brand-text">
                              <LogoTile name={s.legal_name} size={22} />
                              <span className="truncate">{s.legal_name}</span>
                            </Link>
                            <span className="tnum text-right font-semibold" style={{ color: scoreBand(s.composite_score).color }}>
                              {s.composite_score?.toFixed(1)}
                            </span>
                            <span className="tnum text-right">{Math.round(s.growth_potential_score ?? 0)}</span>
                            <span className="tnum hidden text-right sm:block" style={{ color: fraudBand(s.fraud_likelihood_score).color }}>
                              {Math.round(s.fraud_likelihood_score ?? 0)}
                            </span>
                            <span className="tnum text-right text-ink-secondary">{compactUsd(s.total_funding_usd)}</span>
                          </>
                        ) : (
                          <span className="skeleton col-span-full h-4" />
                        )}
                      </m.div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </Tilt>

          {/* floating phone — live data for the top-ranked company */}
          <m.div style={{ y: phoneY }} className="absolute -right-10 -top-16 hidden xl:block">
            <div className="float-a">
              <Phone className="w-[232px]">
                <div className="flex flex-col gap-2.5 px-4 pt-11">
                  <div className="flex items-center gap-2.5">
                    {lead && <LogoTile name={lead.legal_name} size={38} />}
                    <div className="min-w-0">
                      <div className="truncate text-[15px] font-extrabold">{lead?.legal_name ?? "—"}</div>
                      <div className="truncate text-[10.5px] text-ink-muted">
                        {lead ? `${lead.sector} · ${stageLabel(lead.stage)}` : ""}
                      </div>
                    </div>
                  </div>
                  <div className="panel flex items-center justify-between rounded-[14px] p-3.5">
                    <div>
                      <div className="text-[10px] tracking-[0.08em] text-panel-muted">COMPOSITE</div>
                      <div className="tnum text-[32px] font-semibold leading-tight">
                        {leadScore ? Math.round(leadScore.composite_score) : "—"}
                      </div>
                    </div>
                    <svg width="52" height="52" viewBox="0 0 54 54" aria-hidden>
                      <circle cx="27" cy="27" r="22" fill="none" stroke="var(--color-panel-line)" strokeWidth="6" />
                      <m.circle
                        cx="27"
                        cy="27"
                        r="22"
                        fill="none"
                        stroke="var(--color-panel-accent)"
                        strokeWidth="6"
                        strokeLinecap="round"
                        strokeDasharray="138.2"
                        initial={{ strokeDashoffset: 138.2 }}
                        animate={{ strokeDashoffset: 138.2 * (1 - (leadScore?.composite_score ?? 0) / 100) }}
                        transition={{ duration: 1.2, ease: EASE }}
                        transform="rotate(-90 27 27)"
                      />
                    </svg>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniScore label="Growth" value={leadScore?.growth_potential_score ?? null} />
                    <MiniScore label="Safety" value={leadScore?.risk_level_score ?? null} />
                    <MiniScore label="Founder" value={leadScore?.founder_credibility_score ?? null} />
                    <MiniScore label="Fraud ↓" value={leadScore?.fraud_likelihood_score ?? null} invert />
                  </div>
                  {gst !== null && (
                    <div
                      className={`rounded-[10px] border px-2.5 py-2 text-[10.5px] leading-snug ${
                        gst > 0.2
                          ? "border-critical-line bg-critical-tint text-critical-text"
                          : "border-good-line bg-good-tint text-good-text"
                      }`}
                    >
                      {gst > 0.2 ? "Revenue mismatch" : "Revenue within tolerance"} vs the GST figure — {(gst * 100).toFixed(0)}% gap (simulated check).
                    </div>
                  )}
                </div>
              </Phone>
            </div>
          </m.div>
        </m.div>
      </section>

      {/* ───────────────────────────── bento ─────────────────────────────── */}
      <section id="product" className="mx-auto max-w-[1320px] scroll-mt-24 px-5 pb-20 sm:px-8">
        <Reveal className="mb-10 max-w-[720px] space-y-3">
          <Kicker>THE PLATFORM</Kicker>
          <h2 className="text-[34px] font-extrabold leading-[1.1] tracking-[-0.03em] sm:text-[44px]">
            One place to find, verify and rank private companies.
          </h2>
        </Reveal>

        <div className="grid gap-5 lg:grid-cols-3">
          <Reveal className="lg:col-span-2">
            <Spotlight className="panel h-full rounded-[20px] p-7 lg:p-8" color="var(--color-panel-accent)" size={420}>
              <div className="grid gap-6 md:grid-cols-[260px_minmax(0,1fr)]">
                <div className="flex flex-col gap-3">
                  <Kicker onPanel>AI ENGINE</Kicker>
                  <div className="text-[26px] font-extrabold leading-tight tracking-tight">
                    Four independent scores. Every one explained.
                  </div>
                  <div className="text-[14.5px] leading-relaxed text-panel-muted">
                    Growth, safety, founder credibility and fraud are modelled separately, then shown with
                    the features that moved them.
                  </div>
                  {lead && (
                    <Link
                      to={`/startup/${lead.startup_id}`}
                      className="mt-auto inline-flex items-center gap-1.5 pt-2 text-[13.5px] font-semibold text-panel-ink underline-offset-4 hover:underline"
                    >
                      {lead.legal_name}'s live scores <Arrow />
                    </Link>
                  )}
                </div>
                <div className="flex min-w-0 flex-col">
                  <WhenNear className="h-[250px] sm:h-[280px]">
                    {towers && <ScoreTowers scores={towers} theme="dark" className="h-full w-full" />}
                  </WhenNear>
                  <div className="grid grid-cols-4 gap-2 border-t border-panel-line pt-3">
                    {(towers ?? [{ label: "Growth" }, { label: "Safety" }, { label: "Founder" }, { label: "Fraud ↓" }]).map((t) => {
                      const v = "value" in t ? (t.value as number) : null;
                      const inv = "invert" in t && t.invert;
                      const c = v === null ? panelScene.ghost : inv ? fraudColor(panelScene, v) : v >= 75 ? panelScene.strong : v >= 55 ? panelScene.moderate : panelScene.weak;
                      return (
                        <div key={t.label} className="min-w-0 text-center">
                          <div className="flex items-center justify-center gap-1.5 text-[11.5px] text-panel-muted">
                            <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: c }} />
                            <span className="truncate">{t.label}</span>
                          </div>
                          <NumberTicker value={v} className="tnum block text-[24px] font-semibold text-panel-ink" />
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </Spotlight>
          </Reveal>

          <Reveal i={1}>
            <Spotlight className="card card-lit interactive flex h-full flex-col gap-3.5 p-7">
              <FeatureIcon tint="brand">
                <path d="M12 3l7 3v6c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6l7-3z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </FeatureIcon>
              <div className="text-[21px] font-extrabold tracking-tight">Claims, reconciled</div>
              <p className="text-[14.5px] leading-relaxed text-ink-secondary">
                Founder-reported revenue is compared with GST-reported turnover. Over a 20% gap, the profile is
                flagged — with both numbers shown. The turnover figure needs the taxpayer's consent, so
                it is simulated in this build.
              </p>
              <div className="mt-auto rounded-xl border border-critical-line bg-critical-tint p-3 text-[13px] leading-snug text-critical-text">
                <b>Why both numbers?</b> A 45% gap means something different on $50K than on $50M.
              </div>
            </Spotlight>
          </Reveal>

          <Reveal i={0}>
            <Spotlight className="card card-lit interactive flex h-full flex-col gap-3.5 p-7">
              <FeatureIcon tint="brand">
                <circle cx="8" cy="8" r="3.5" stroke="currentColor" strokeWidth="2" />
                <circle cx="16" cy="16" r="3.5" stroke="currentColor" strokeWidth="2" />
                <path d="M10.5 10.5l3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </FeatureIcon>
              <div className="text-[21px] font-extrabold tracking-tight">Matched to your mandate</div>
              <p className="text-[14.5px] leading-relaxed text-ink-secondary">
                Ranked by your sectors, stages and cheque size, sharpened by what you open, save and dismiss.
              </p>
              {matches[0] && (
                <div className="mt-auto space-y-2">
                  <div className="truncate text-[12px] font-semibold text-ink-secondary">
                    Top match: {matches[0].startup.legal_name}
                  </div>
                  {[
                    { l: "Mandate", v: matches[0].preference_score },
                    { l: "Behaviour", v: matches[0].behavioral_score },
                    { l: "Quality", v: matches[0].quality_score },
                  ].map((b) => (
                    <div key={b.l} className="flex items-center gap-2.5 text-[12px]">
                      <span className="w-16 text-ink-muted">{b.l}</span>
                      <div className="h-1.5 flex-1 rounded-full bg-track">
                        <m.div
                          className="h-1.5 rounded-full bg-brand"
                          initial={{ width: 0 }}
                          whileInView={{ width: `${Math.max(2, b.v)}%` }}
                          viewport={{ once: true }}
                          transition={{ duration: 0.9, ease: EASE }}
                        />
                      </div>
                      <span className="tnum w-6 text-right text-ink-muted">{Math.round(b.v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Spotlight>
          </Reveal>

          <Reveal i={1}>
            <Spotlight className="card card-lit interactive flex h-full flex-col gap-3.5 p-7" color="var(--color-serious)">
              <FeatureIcon tint="serious">
                <path d="M12 4l9 16H3l9-16z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                <path d="M12 10v4M12 17h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </FeatureIcon>
              <div className="text-[21px] font-extrabold tracking-tight">Anomalies surfaced</div>
              <p className="text-[14.5px] leading-relaxed text-ink-secondary">
                An Isolation Forest and a reconstruction model learn what normal looks like and raise the
                profiles that don't fit.
              </p>
              {fraudHist && (
                <figure className="m-0 mt-auto">
                  <div className="flex h-16 items-end gap-[2px]" role="img" aria-label={`Fraud score histogram: ${fraudHist.join(", ")} companies per 10-point bin`}>
                    {fraudHist.map((c, i) => {
                      const max = Math.max(...fraudHist);
                      return (
                        <m.div
                          key={i}
                          title={`Fraud ${i * 10}–${i * 10 + 10}: ${c} companies`}
                          className={`flex-1 rounded-t-[3px] ${i >= 4 ? "bg-serious" : i === 3 ? "bg-warning" : "bg-line-strong"}`}
                          initial={{ height: 0 }}
                          whileInView={{ height: `${Math.max(3, Math.sqrt(c / max) * 100)}%` }}
                          viewport={{ once: true }}
                          transition={{ duration: 0.7, delay: i * 0.04, ease: EASE }}
                        />
                      );
                    })}
                  </div>
                  <figcaption className="mt-1.5 flex justify-between text-[11.5px] text-ink-muted">
                    <span>Fraud 0</span>
                    <span className="tnum">{fmt(flaggedInSample)} of {fmt(sky?.count)} sampled ≥ 35</span>
                    <span>100</span>
                  </figcaption>
                </figure>
              )}
            </Spotlight>
          </Reveal>

          <Reveal i={2}>
            <Spotlight className="card card-lit interactive flex h-full flex-col gap-3.5 p-7">
              <FeatureIcon tint="brand">
                <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </FeatureIcon>
              <div className="text-[21px] font-extrabold tracking-tight">Benchmarked against peers</div>
              <p className="text-[14.5px] leading-relaxed text-ink-secondary">
                Retrieval finds the ten closest companies at the same stage and sector — and says so when
                the cohort is too thin to trust.
              </p>
              <div className="mt-auto rounded-xl border border-warning-line bg-warning-tint px-3 py-2.5 text-[12.5px] text-warning-text">
                <b>Low confidence</b> is shown, never hidden, when a cohort has fewer than 20 peers.
              </div>
            </Spotlight>
          </Reveal>
        </div>
      </section>

      {/* ───────────────────────────── how it works ──────────────────────── */}
      <section id="how" className="scroll-mt-20 border-y border-line bg-surface">
        <div className="mx-auto grid max-w-[1320px] gap-12 px-5 py-20 sm:px-8 lg:grid-cols-[400px_minmax(0,1fr)] lg:gap-14 lg:py-24">
          <Reveal className="space-y-4">
            <Kicker>HOW IT WORKS</Kicker>
            <h2 className="text-[34px] font-extrabold leading-[1.1] tracking-[-0.03em] sm:text-[42px]">
              An agent that decides what to check next.
            </h2>
            <p className="text-[16.5px] leading-relaxed text-ink-secondary">
              Not a fixed script. The verification agent reads what's missing on a profile, picks the
              sources worth querying, and escalates when a check fails.
            </p>
            <ol className="space-y-4 pt-3">
              {[
                ["Register", "Stage-aware forms ask only for metrics that exist at that stage."],
                ["Verify", "The agent cross-checks registry, tax and founder records."],
                ["Score & match", "Four scores, a composite, and a ranked feed for each investor."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3.5">
                  <span className="tnum grid h-9 w-9 shrink-0 place-items-center rounded-full bg-panel text-[13px] text-panel-ink ring-1 ring-panel-line">
                    {i + 1}
                  </span>
                  <div>
                    <div className="text-[15.5px] font-bold">{t}</div>
                    <div className="text-[14px] leading-relaxed text-ink-muted">{d}</div>
                  </div>
                </li>
              ))}
            </ol>
          </Reveal>

          <Reveal i={1} className="min-w-0 self-center">
            <div className="panel overflow-hidden rounded-[20px] shadow-[var(--shadow-float)]">
              <div className="flex flex-wrap items-center gap-2.5 border-b border-panel-line px-5 py-3.5 text-[13.5px]">
                <span className="pulse-ring h-2.5 w-2.5 rounded-full bg-panel-accent" />
                <span className="font-bold">Agent trace</span>
                <span className="truncate text-panel-muted">{lead ? `· ${lead.legal_name}` : ""}</span>
                <span className="ml-auto text-[12px] text-panel-muted">latest record per source</span>
              </div>
              <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <WhenNear className="h-[280px] border-panel-line md:h-auto md:min-h-[320px] md:border-r">
                  {steps.length > 0 && <AgentGraph steps={steps} theme="dark" className="h-full w-full" />}
                </WhenNear>
                <div className="flex flex-col gap-2 p-5 text-[13px]">
                  <div className="tnum text-[12px] text-panel-muted">
                    {steps.length ? `plan → ${steps.map((s) => s.source.toLowerCase()).join(" → ")}` : "Loading trace…"}
                  </div>
                  {trace.map((r, i) => (
                    <m.div
                      key={r.enrichment_id}
                      initial={{ opacity: 0, x: 16 }}
                      whileInView={{ opacity: 1, x: 0 }}
                      viewport={{ once: true }}
                      transition={{ delay: 0.1 + i * 0.08 }}
                      className={`grid grid-cols-[76px_minmax(0,1fr)_56px] items-center gap-2 rounded-[10px] border px-3 py-2 ${
                        r.is_mock ? "border-transparent bg-panel-raised" : "border-panel-accent/30 bg-panel-accent/10"
                      }`}
                    >
                      <span className="font-semibold">{SOURCE_NAME[r.source] ?? r.source}</span>
                      <span className="truncate text-panel-muted">
                        {r.status}
                        {r.error ? ` — ${r.error}` : ""} · {apiDate(r.retrieved_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                      </span>
                      <span className={`text-right font-semibold ${r.is_mock ? "text-panel-warn" : "text-panel-accent"}`}>
                        {r.is_mock ? "mocked" : "live"}
                      </span>
                    </m.div>
                  ))}
                  {leadScore && (
                    <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-panel-line pt-3">
                      <span className="text-panel-muted">Founder credibility</span>
                      <span className="tnum text-[18px] font-semibold text-panel-accent">
                        {Math.round(leadScore.founder_credibility_score)}
                      </span>
                      <span className="ml-auto text-panel-muted">Composite</span>
                      <span className="tnum text-[18px] font-semibold text-panel-accent">
                        {leadScore.composite_score.toFixed(1)}
                      </span>
                    </div>
                  )}
                  {lead && (
                    <Link to={`/startup/${lead.startup_id}`} className="text-[12.5px] font-semibold text-panel-ink underline-offset-4 hover:underline">
                      Run the agent yourself on this profile →
                    </Link>
                  )}
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ───────────────────────────── mobile ────────────────────────────── */}
      <section id="mobile" className="mx-auto grid max-w-[1320px] scroll-mt-20 items-center gap-12 px-5 py-20 sm:px-8 lg:grid-cols-[minmax(0,1fr)_520px] lg:py-24">
        <div className="relative mx-auto h-[600px] w-full max-w-[580px]">
          <div
            aria-hidden
            className="absolute inset-x-5 inset-y-10 rounded-[40px]"
            style={{ background: "radial-gradient(circle at 50% 45%, var(--color-hero-glow), transparent 70%)" }}
          />
          <m.div
            initial={{ opacity: 0, rotate: -12, y: 40 }}
            whileInView={{ opacity: 1, rotate: -6, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.9, ease: EASE }}
            className="absolute left-0 top-5 hidden sm:left-[2%] sm:block"
          >
            <div className="float-b">
              <Phone>
                <div className="flex flex-col gap-2 px-3.5 pt-12">
                  <div className="text-[17px] font-extrabold">Your matches</div>
                  {matches.map((mt) => (
                    <div key={mt.startup.startup_id} className="rounded-xl border border-line bg-surface p-2.5">
                      <div className="flex justify-between gap-2">
                        <b className="truncate text-[13px]">{mt.startup.legal_name}</b>
                        <span className="tnum font-semibold text-brand-text">{Math.round(mt.match_score)}</span>
                      </div>
                      <div className="mt-0.5 truncate text-[10.5px] text-ink-muted">{mt.reasons[0]}</div>
                    </div>
                  ))}
                  {!matches.length && <div className="text-[12px] text-ink-muted">Create an investor profile to see matches.</div>}
                </div>
              </Phone>
            </div>
          </m.div>
          <m.div
            initial={{ opacity: 0, rotate: 12, y: 60 }}
            whileInView={{ opacity: 1, rotate: 5, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.9, delay: 0.15, ease: EASE }}
            className="absolute left-1/2 top-6 -translate-x-1/2 sm:left-auto sm:right-[2%] sm:top-14 sm:translate-x-0"
          >
            <div className="float-a">
              <Phone>
                <div className="flex h-full flex-col gap-2.5 bg-surface px-3.5 pt-12">
                  <div className="text-[17px] font-extrabold">Needs review</div>
                  {mandateAlerts.map((a) => (
                    <div
                      key={a.signal_id}
                      className={`rounded-xl border p-2.5 ${
                        a.severity === "high" ? "border-critical-line bg-critical-tint" : "border-warning-line bg-warning-tint"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <b className="truncate text-[13px]">{a.startup_name}</b>
                        <span
                          className={`rounded-full px-1.5 py-px text-[9.5px] font-bold uppercase ${
                            a.severity === "high" ? "text-critical-text" : "text-warning-text"
                          }`}
                        >
                          {a.severity}
                        </span>
                      </div>
                      <div className="mt-1 line-clamp-2 text-[10.5px] leading-snug text-ink-secondary">{a.explanation}</div>
                    </div>
                  ))}
                  <div className="rounded-xl border border-good-line bg-good-tint p-2.5 text-[10.5px] leading-snug text-good-text">
                    Algorithms raise these flags; a person reviews each one.
                  </div>
                </div>
              </Phone>
            </div>
          </m.div>
        </div>

        <Reveal className="space-y-4">
          <Kicker>ON THE GO</Kicker>
          <h2 className="text-[34px] font-extrabold leading-[1.1] tracking-[-0.03em] sm:text-[42px]">
            Your deal flow, in your pocket.
          </h2>
          <p className="text-[16.5px] leading-relaxed text-ink-secondary">
            The same evidence on a phone as on a desktop. Scores, provenance and fraud flags reflow —
            they're never dropped to save space.
          </p>
          <ul className="space-y-2.5 pt-2 text-[15px]">
            <li className="flex items-center gap-2.5"><Tick />Ranked matches with the reason for each</li>
            <li className="flex items-center gap-2.5"><Tick />Fraud alerts scoped to your sectors</li>
            <li className="flex items-center gap-2.5"><Tick />Every score one tap from its explanation</li>
          </ul>
        </Reveal>
      </section>

      {/* ───────────────────────────── model ─────────────────────────────── */}
      <section id="model" className="mx-auto grid max-w-[1320px] scroll-mt-20 gap-5 px-5 pb-20 sm:px-8 lg:grid-cols-2">
        <Reveal>
          <Spotlight className="card card-lit flex h-full flex-col gap-3.5 p-8">
            <Kicker>MODEL TRANSPARENCY</Kicker>
            <h2 className="text-[30px] font-extrabold leading-[1.12] tracking-[-0.03em] sm:text-[34px]">
              We publish our own numbers.
            </h2>
            <p className="text-[15.5px] leading-relaxed text-ink-secondary">
              Trained on {fmt(metrics?.n_labelled)} labelled Y Combinator outcomes. Active companies are
              excluded — their outcome hasn't resolved yet.
            </p>
            <p className="border-l-[3px] border-line-strong pl-3 text-[13px] leading-relaxed text-ink-muted">
              Applying a global model to Indian startups is a domain transfer, and the product says so.
            </p>
            <Link to="/model" className="group mt-auto inline-flex items-center gap-1.5 pt-2 text-[14.5px] font-bold text-brand-text">
              See full model report
              <span className="transition-transform group-hover:translate-x-1">
                <Arrow />
              </span>
            </Link>
          </Spotlight>
        </Reveal>
        <Reveal i={1} className="card card-lit overflow-x-auto">
          <table className="data-table min-w-[420px]">
            <thead>
              <tr>
                <th className="text-left">Model</th>
                <th className="text-right">AUROC</th>
                <th className="text-right">Bal. acc</th>
                <th className="text-right">F1</th>
              </tr>
            </thead>
            <tbody>
              {metrics?.comparison ? (
                Object.entries(metrics.comparison as Record<string, any>)
                  .sort((a, b) => b[1].auroc - a[1].auroc)
                  .map(([name, v]) => (
                    <tr key={name} className={name === metrics.chosen_model ? "bg-row-selected" : ""}>
                      <td className="text-[15px]">
                        <span className="font-bold capitalize">{name.replace(/_/g, " ")}</span>
                        {name === metrics.chosen_model && (
                          <span className="ml-2 rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-bold text-brand-text">
                            SELECTED
                          </span>
                        )}
                      </td>
                      <td className="tnum text-right text-[15px] font-semibold">{v.auroc.toFixed(4)}</td>
                      <td className="tnum text-right text-[15px]">{v.balanced_accuracy.toFixed(4)}</td>
                      <td className="tnum text-right text-[15px]">{v.f1.toFixed(4)}</td>
                    </tr>
                  ))
              ) : (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-ink-muted">Loading model metrics…</td>
                </tr>
              )}
            </tbody>
          </table>
        </Reveal>
      </section>

      {/* ───────────────────────────── CTA ───────────────────────────────── */}
      <section className="mx-auto max-w-[1320px] px-5 pb-20 sm:px-8">
        <Reveal className="beam relative flex flex-col items-start gap-8 overflow-hidden rounded-[28px] bg-cta p-9 sm:p-14 lg:flex-row lg:items-center">
          <div aria-hidden className="dot-grid absolute inset-0 opacity-20 [mask-image:linear-gradient(90deg,transparent,#000)]" />
          <div
            aria-hidden
            className="absolute -bottom-40 -right-20 h-[520px] w-[520px] rounded-full border-[70px] border-white/10"
          />
          <div className="relative max-w-[720px] space-y-3">
            <h2 className="text-[34px] font-extrabold leading-[1.08] tracking-[-0.03em] text-white sm:text-[46px]">
              Stop trusting the pitch deck.
            </h2>
            <p className="text-[17px] leading-relaxed text-white sm:text-[18px]">
              Open the platform and run the verification agent on any company.
            </p>
          </div>
          <Sheen className="relative rounded-xl lg:ml-auto">
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-2 rounded-xl bg-white px-6 py-3.5 text-[16px] font-extrabold text-[#0b1b36] transition-transform hover:-translate-y-0.5 active:translate-y-0"
            >
              Open the platform <Arrow />
            </Link>
          </Sheen>
        </Reveal>
      </section>

      {/* ───────────────────────────── footer ────────────────────────────── */}
      <footer className="border-t border-panel-line bg-panel text-panel-muted">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-9 text-[13.5px] sm:px-8">
          <span className="text-[17px] font-extrabold text-panel-ink">VentureIQ</span>
          <span>B.E. dissertation — BMS College of Engineering, 2025–26</span>
          <span className="lg:ml-auto">Marketplace flows are simulated · Some enrichment sources are mocked</span>
        </div>
      </footer>
    </div>
  );
}

function FeatureIcon({ children, tint }: { children: ReactNode; tint: "brand" | "serious" }) {
  return (
    <div
      className={`grid h-11 w-11 place-items-center rounded-xl transition-transform duration-300 group-hover:scale-105 ${
        tint === "brand" ? "bg-brand-tint text-brand-text" : "bg-serious-tint text-serious"
      }`}
    >
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
        {children}
      </svg>
    </div>
  );
}
