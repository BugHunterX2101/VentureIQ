import { useCallback, useEffect, useMemo, useState } from "react";
import { NumberTicker } from "../components/ui/effects";
import { Link } from "react-router-dom";
import { api, type Alert, type Match, type PlatformStats } from "../lib/api";
import {
  compactNum,
  compactUsd,
  fraudBand,
  relativeTime,
  scoreBand,
  stageLabel,
  apiDate,
} from "../lib/format";
import { BarChart, HBarChart, LineChart } from "../components/charts";
import {
  Badge,
  Card,
  Empty,
  LabeledDivider,
  LogoTile,
  SectionError,
  SectionHeader,
  Stat,
  VerifiedBadge,
} from "../components/primitives";
import { useInvestor } from "../lib/investor-context";

const LAST_VISIT_KEY = "viq.lastVisit";

/** Median, not mean: one outlier match should not move the headline number. */
function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

const SEVERITY_TONE: Record<string, { box: string; badge: "critical" | "serious" | "warning" }> = {
  high: { box: "border-critical-line bg-critical-tint", badge: "critical" },
  medium: { box: "border-serious-line bg-serious-tint", badge: "serious" },
  low: { box: "border-warning-line bg-warning-tint", badge: "warning" },
};

export default function Overview() {
  const { current, track } = useInvestor();

  const [matches, setMatches] = useState<Match[] | null>(null);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [activity, setActivity] = useState<any[] | null>(null);
  const [personalErr, setPersonalErr] = useState<string | null>(null);
  const [personalLoading, setPersonalLoading] = useState(true);

  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [sectors, setSectors] = useState<any[]>([]);
  const [stages, setStages] = useState<any[]>([]);
  const [dist, setDist] = useState<any[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [cities, setCities] = useState<any[]>([]);
  const [corpusErr, setCorpusErr] = useState<string | null>(null);
  const [corpusLoading, setCorpusLoading] = useState(true);
  const [showCorpus, setShowCorpus] = useState(false);

  const [lastVisit] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(LAST_VISIT_KEY);
      return raw ? Number(raw) : 0;
    } catch {
      return 0;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(LAST_VISIT_KEY, String(Date.now()));
    } catch {
      /* storage unavailable — "since last visit" simply won't show */
    }
  }, []);

  const loadCorpus = useCallback(() => {
    setCorpusLoading(true);
    setCorpusErr(null);
    Promise.all([
      api.stats(),
      api.sectorStats(),
      api.stageStats(),
      api.scoreDistribution(),
      api.fundingTimeline(),
      api.cities(),
    ])
      .then(([s, sec, stg, d, t, c]) => {
        setStats(s);
        setSectors(sec);
        setStages(stg);
        setDist(d);
        setTimeline(t.filter((x: any) => x.year >= 2015));
        setCities(c);
      })
      .catch((e) => setCorpusErr(String(e?.message ?? e)))
      .finally(() => setCorpusLoading(false));
  }, []);

  const loadPersonal = useCallback(() => {
    if (!current) {
      setPersonalLoading(false);
      return;
    }
    setPersonalLoading(true);
    setPersonalErr(null);
    Promise.all([
      api.feed(current.investor_id, { limit: 40 }),
      api.alerts(60),
      api.activity(current.investor_id),
    ])
      .then(([f, a, act]) => {
        setMatches(f);
        setAlerts(a);
        setActivity(act);
      })
      .catch((e) => setPersonalErr(String(e?.message ?? e)))
      .finally(() => setPersonalLoading(false));
  }, [current]);

  useEffect(() => loadCorpus(), [loadCorpus]);
  useEffect(() => loadPersonal(), [loadPersonal]);

  const pref = current?.preference;

  const myAlerts = useMemo(() => {
    if (!alerts) return [];
    const mine = pref?.preferred_sectors ?? [];
    if (!mine.length) return alerts;
    return alerts.filter((a) => mine.includes(a.sector));
  }, [alerts, pref]);

  const newAlertCount = useMemo(
    () => (lastVisit ? myAlerts.filter((a) => apiDate(a.run_at).getTime() > lastVisit).length : 0),
    [myAlerts, lastVisit],
  );

  const savedCount = useMemo(
    () => (activity ?? []).filter((e) => ["save", "interest_expressed"].includes(e.event_type)).length,
    [activity],
  );
  const lastActivityAt = activity?.[0]?.occurred_at as string | undefined;
  const strongMatches = useMemo(() => (matches ?? []).filter((m) => m.match_score >= 60), [matches]);
  const medianMatchQuality = useMemo(
    () => median((matches ?? []).slice(0, 20).map((m) => m.quality_score)),
    [matches],
  );
  const highSeverity = myAlerts.filter((a) => a.severity === "high").length;
  const coldStart = matches?.[0]?.cold_start ?? false;
  const topMatches = (matches ?? []).filter((m) => m.reasons.length > 0).slice(0, 8);

  const timelineWithGap = useMemo(() => {
    if (!timeline.length) return [];
    const byYear = new Map(timeline.map((t: any) => [t.year, t.rounds]));
    const years = timeline.map((t: any) => t.year);
    const out: { label: number; value: number | null }[] = [];
    for (let y = Math.min(...years); y <= Math.max(...years); y++) {
      out.push({ label: y, value: byYear.has(y) ? (byYear.get(y) as number) : null });
    }
    return out;
  }, [timeline]);
  const hasGap = timelineWithGap.some((t) => t.value === null);

  return (
    <div className="animate-in space-y-6">
      {/* ─────────────────────────── greeting ─────────────────────────── */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">
            {current ? `Welcome back, ${current.name.split(" ")[0]}` : "Investment intelligence"}
          </h1>
          <p className="mt-1 text-[14.5px] text-ink-muted">
            {current
              ? "Verified, explainable deal intelligence matched to your mandate."
              : "Create an investor profile to get a personalised deal feed."}
          </p>
        </div>
        {current && (
          <div className="flex flex-wrap items-center gap-1.5">
            {pref?.stage_preference.slice(0, 2).map((s) => (
              <span key={s} className="chip">
                {stageLabel(s)}
              </span>
            ))}
            {pref?.risk_tolerance && <span className="chip capitalize">{pref.risk_tolerance} risk</span>}
            <Badge tone={current.kyc_status === "verified" ? "good" : "warning"}>KYC {current.kyc_status}</Badge>
          </div>
        )}
      </div>

      {!current ? (
        <Card>
          <Empty
            title="No investor profile selected"
            hint="Your mandate is the entire ranking signal until behavioural learning kicks in."
            action={
              <Link to="/onboarding" className="btn btn-primary">
                Set up profile
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          {/* ─────────────────────────── KPIs ─────────────────────────── */}
          {personalLoading ? (
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="skeleton h-[124px]" />
              ))}
            </div>
          ) : personalErr ? (
            <Card>
              <SectionError message={personalErr} onRetry={loadPersonal} />
            </Card>
          ) : (
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <Stat
                to="/feed"
                label="Matches for you"
                value={<NumberTicker value={strongMatches.length} format={compactNum} />}
                sub={`of ${compactNum(matches?.length ?? 0)} ranked for your mandate`}
              />
              <Stat
                to="/alerts"
                label="Needs review"
                value={<NumberTicker value={myAlerts.length} format={compactNum} />}
                accent={myAlerts.length ? "var(--color-serious)" : undefined}
                delta={newAlertCount ? { value: newAlertCount, sentiment: "bad" } : undefined}
                sub={highSeverity ? `${highSeverity} high severity · in your sectors` : "in your sectors"}
              />
              <Stat
                label="Tracking"
                value={<NumberTicker value={savedCount} format={compactNum} />}
                sub={lastActivityAt ? `last activity ${relativeTime(lastActivityAt)}` : "no saved companies yet"}
              />
              <Stat
                label="Median match quality"
                value={<NumberTicker value={medianMatchQuality} format={(n) => n.toFixed(1)} />}
                sub={stats?.avg_composite_score ? `corpus mean ${stats.avg_composite_score.toFixed(1)}` : "composite of your top 20"}
              />
            </div>
          )}

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
            {/* ─────────────────────── top opportunities ─────────────────────── */}
            <Card className="min-w-0 overflow-hidden">
              <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
                <div className="min-w-0">
                  <h2 className="text-[17px] font-bold">Top opportunities</h2>
                  <p className="text-[13px] text-ink-muted">Ranked by mandate, behaviour, network and quality</p>
                </div>
                <div className="ml-auto flex items-center gap-3">
                  {coldStart && <Badge tone="warning">Stated mandate only</Badge>}
                  <Link to="/feed" className="text-[13.5px] font-bold text-brand-text hover:underline">
                    View all
                  </Link>
                </div>
              </div>

              {personalLoading ? (
                <div className="space-y-2 p-5">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="skeleton h-12" />
                  ))}
                </div>
              ) : personalErr ? (
                <SectionError message={personalErr} onRetry={loadPersonal} />
              ) : topMatches.length === 0 ? (
                <Empty
                  title="No matches yet"
                  hint="Broaden your mandate — add sectors or stages — to see ranked opportunities."
                  action={
                    <Link to="/onboarding" className="btn">
                      Edit mandate
                    </Link>
                  }
                />
              ) : (
                <>
                <ul className="divide-y divide-grid md:hidden">
                  {topMatches.map((m) => (
                    <li key={m.startup.startup_id}>
                      <Link
                        to={`/startup/${m.startup.startup_id}`}
                        onClick={() => track("view", m.startup.startup_id)}
                        className="flex items-center gap-3 px-4 py-3"
                      >
                        <LogoTile name={m.startup.legal_name} src={m.startup.logo_url} size={36} />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="truncate text-[14px] font-bold">{m.startup.legal_name}</span>
                            <VerifiedBadge verified={m.startup.verified} compact />
                          </span>
                          <span className="block truncate text-[12px] text-ink-muted">{m.reasons[0]}</span>
                          <span className="tnum mt-0.5 block text-[12px] text-ink-secondary">
                            Score{" "}
                            <b style={{ color: scoreBand(m.startup.composite_score).color }}>
                              {m.startup.composite_score === null ? "—" : Math.round(m.startup.composite_score)}
                            </b>
                            {" · "}Fraud{" "}
                            <b style={{ color: fraudBand(m.startup.fraud_likelihood_score).color }}>
                              {m.startup.fraud_likelihood_score === null ? "—" : Math.round(m.startup.fraud_likelihood_score)}
                            </b>
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          <span className="tnum block text-[20px] font-semibold leading-none text-brand-text">
                            {Math.round(m.match_score)}
                          </span>
                          <span className="text-[10px] font-bold uppercase tracking-wide text-ink-muted">match</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
                <div className="hidden overflow-x-auto md:block">
                  <table className="data-table min-w-[640px]">
                    <thead>
                      <tr>
                        <th className="text-left">Organization</th>
                        <th className="text-left">Why it matches</th>
                        <th className="text-right">Match</th>
                        <th className="text-right">Score</th>
                        <th className="text-right">Fraud ↓</th>
                      </tr>
                    </thead>
                    <tbody>
                      {topMatches.map((m) => (
                        <tr key={m.startup.startup_id}>
                          <td>
                            <Link
                              to={`/startup/${m.startup.startup_id}`}
                              onClick={() => track("view", m.startup.startup_id)}
                              className="flex min-w-0 items-center gap-3"
                            >
                              <LogoTile name={m.startup.legal_name} src={m.startup.logo_url} size={34} />
                              <span className="min-w-0">
                                <span className="flex items-center gap-1.5">
                                  <span className="max-w-[200px] truncate font-bold text-ink hover:text-brand-text">
                                    {m.startup.legal_name}
                                  </span>
                                  <VerifiedBadge verified={m.startup.verified} compact />
                                </span>
                                <span className="block truncate text-[12px] text-ink-muted">
                                  {m.startup.sector} · {stageLabel(m.startup.stage)}
                                  {m.startup.hq_city ? ` · ${m.startup.hq_city}` : ""}
                                </span>
                              </span>
                            </Link>
                          </td>
                          <td className="max-w-[240px] text-[12.5px] text-ink-secondary">
                            <span className="line-clamp-2">{m.reasons[0]}</span>
                          </td>
                          <td className="tnum text-right font-bold text-brand-text">{Math.round(m.match_score)}</td>
                          <td className="tnum text-right" style={{ color: scoreBand(m.startup.composite_score).color }}>
                            {m.startup.composite_score === null ? "—" : Math.round(m.startup.composite_score)}
                          </td>
                          <td className="tnum text-right" style={{ color: fraudBand(m.startup.fraud_likelihood_score).color }}>
                            {m.startup.fraud_likelihood_score === null ? "—" : Math.round(m.startup.fraud_likelihood_score)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
            </Card>

            {/* ─────────────────────── needs review ─────────────────────── */}
            <Card className="min-w-0 p-5">
              <SectionHeader
                title="Needs review"
                description="Flags in your sectors. Algorithms flag; a human decides."
                action={
                  <Link to="/alerts" className="text-[13.5px] font-bold text-brand-text hover:underline">
                    View all
                  </Link>
                }
              />
              {personalLoading ? (
                <div className="space-y-2.5">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="skeleton h-[84px]" />
                  ))}
                </div>
              ) : personalErr ? (
                <SectionError message={personalErr} onRetry={loadPersonal} />
              ) : myAlerts.length === 0 ? (
                <Empty
                  tone="good"
                  title="Nothing in your sectors needs review"
                  hint="Every cross-source consistency check passed for your mandate."
                />
              ) : (
                <div className="space-y-2.5">
                  {myAlerts.slice(0, 4).map((a) => {
                    const t = SEVERITY_TONE[a.severity] ?? SEVERITY_TONE.low;
                    return (
                      <Link
                        key={a.signal_id}
                        to={`/startup/${a.startup_id}`}
                        onClick={() => track("view", a.startup_id)}
                        className={`block rounded-xl border p-3.5 transition-shadow hover:shadow-[var(--shadow-hover)] ${t.box}`}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[14px] font-bold text-ink">{a.startup_name}</span>
                          <Badge tone={t.badge}>{a.severity}</Badge>
                          <span className="ml-auto text-[12px] text-ink-secondary">{a.sector}</span>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-[12.5px] leading-snug text-ink-secondary">{a.explanation}</p>
                        <p className="tnum mt-1 text-[11.5px] text-ink-muted">{relativeTime(a.run_at)}</p>
                      </Link>
                    );
                  })}
                </div>
              )}
            </Card>
          </div>

          {/* ─────────────────── platform context (demoted) ─────────────────── */}
          <div className="pt-2">
            <LabeledDivider>Platform context · how the corpus looks overall</LabeledDivider>
          </div>

          <button
            className="btn w-full md:hidden"
            onClick={() => setShowCorpus((v) => !v)}
            aria-expanded={showCorpus}
          >
            {showCorpus ? "Hide platform context" : "Show platform context"}
          </button>

          <div className={`${showCorpus ? "" : "hidden"} space-y-5 md:block`}>
            {corpusErr ? (
              <Card>
                <SectionError message={corpusErr} onRetry={loadCorpus} />
              </Card>
            ) : corpusLoading ? (
              <div className="skeleton h-[260px]" />
            ) : (
              <>
                <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
                  <Stat label="Startups indexed" value={<NumberTicker value={stats?.startups} format={compactNum} />} sub={`${compactNum(stats?.verified)} registry-verified`} />
                  <Stat label="Capital tracked" value={<NumberTicker value={stats?.total_tracked_funding_usd} format={compactUsd} />} sub="across all recorded rounds" />
                  <Stat
                    label="Flagged corpus-wide"
                    value={<NumberTicker value={stats?.flagged_startups} format={compactNum} />}
                    sub={stats?.startups ? `${((stats.flagged_startups / stats.startups) * 100).toFixed(1)}% of corpus` : undefined}
                  />
                  <Stat label="Mean composite" value={<NumberTicker value={stats?.avg_composite_score} format={(n) => n.toFixed(1)} />} sub={`${compactNum(stats?.behavioral_events)} behavioural events`} />
                </div>

                <div className="grid gap-5 xl:grid-cols-3">
                  <Card className="min-w-0 p-5 xl:col-span-2">
                    <SectionHeader
                      title="Composite score distribution"
                      description="A broad spread means the score is actually discriminating between companies."
                    />
                    <BarChart
                      data={dist.map((d) => ({ label: String(d.lower), value: d.count, sublabel: `score ${d.bucket}` }))}
                      valueFormat={(v) => `${compactNum(v)} startups`}
                      height={200}
                    />
                  </Card>
                  <Card className="min-w-0 p-5">
                    <SectionHeader title="Stage mix" description="Companies per stage, with the mean score." />
                    <HBarChart
                      data={stages.map((s) => ({
                        label: stageLabel(s.stage),
                        value: s.count,
                        meta: s.avg_composite_score ? `avg ${s.avg_composite_score}` : undefined,
                      }))}
                      valueFormat={compactNum}
                    />
                  </Card>
                </div>

                <div className="grid gap-5 lg:grid-cols-3">
                  <Card className="min-w-0 p-5">
                    <SectionHeader title="Largest sectors" description="By company count, with the mean score." />
                    <HBarChart
                      data={sectors.slice(0, 8).map((s) => ({
                        label: s.sector,
                        value: s.count,
                        meta: s.avg_composite_score ? `avg ${s.avg_composite_score}` : undefined,
                      }))}
                      valueFormat={compactNum}
                    />
                  </Card>
                  <Card className="min-w-0 p-5">
                    <SectionHeader title="Startup hubs" description="Where indexed companies are headquartered." />
                    <HBarChart
                      data={cities.slice(0, 8).map((c) => ({ label: c.city, value: c.count }))}
                      valueFormat={compactNum}
                    />
                  </Card>
                  <Card className="min-w-0 p-5">
                    <SectionHeader title="Funding rounds per year" description="From the seeded Indian funding dataset." />
                    {timelineWithGap.length > 1 && (
                      <div className="pb-4">
                        <LineChart
                          data={timelineWithGap}
                          valueFormat={(v) => `${v} rounds`}
                          height={200}
                          gapNote={hasGap ? "The line breaks where the source datasets have no records." : undefined}
                        />
                      </div>
                    )}
                  </Card>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
