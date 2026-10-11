import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, m } from "motion/react";
import { api, type Stage } from "../lib/api";
import { STAGE_LABEL, scoreBand } from "../lib/format";
import { Card, LogoTile } from "../components/primitives";
import { useAuth } from "../lib/auth";
import { useInvestor } from "../lib/investor-context";

const SECTORS = [
  "FinTech", "Enterprise Software", "AI / ML", "HealthTech", "E-Commerce",
  "Consumer Internet", "EdTech", "Logistics & Mobility", "AgriTech",
  "ClimateTech", "PropTech", "Gaming & Media", "Food & Beverage", "Industrials",
];
const CITIES = ["Bangalore", "Mumbai", "Delhi", "Pune", "Hyderabad", "Chennai", "Gurgaon"];
const STAGES: Stage[] = ["idea", "seed", "series_a", "series_b_plus", "growth"];

const STEPS = [
  { id: "identity", title: "Who you are", blurb: "So founders know who is looking." },
  { id: "mandate", title: "What you invest in", blurb: "The whole ranking signal on day one." },
  { id: "cheque", title: "Cheque size & risk", blurb: "How far down the risk curve you go." },
];

function Chips({
  items,
  selected,
  onToggle,
  label,
}: {
  items: string[];
  selected: string[];
  onToggle: (v: string) => void;
  label?: (v: string) => string;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((v) => {
        const on = selected.includes(v);
        return (
          <m.button
            key={v}
            type="button"
            onClick={() => onToggle(v)}
            aria-pressed={on}
            whileTap={{ scale: 0.94 }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
            className={`cursor-pointer rounded-full border px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
              on
                ? "border-brand bg-brand-tint text-brand-text"
                : "border-line bg-raised text-ink-secondary hover:border-line-strong hover:text-ink"
            }`}
          >
            {label ? label(v) : v}
          </m.button>
        );
      })}
    </div>
  );
}

/** What the mandate reaches, counted against the live corpus as it is edited.
 *  A form that shows its own consequences beats a form that promises one. */
function LivePreview({
  sectors,
  stages,
  cities,
}: {
  sectors: string[];
  stages: string[];
  cities: string[];
}) {
  const [data, setData] = useState<{ matches: number; sample: any[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    setLoading(true);
    // Debounced: a chip tap should not fire a query per keystroke-equivalent.
    timer.current = window.setTimeout(() => {
      api
        .mandatePreview({ sectors, stages, cities })
        .then(setData)
        .catch(() => setData(null))
        .finally(() => setLoading(false));
    }, 320);
    return () => window.clearTimeout(timer.current);
  }, [sectors, stages, cities]);

  return (
    <Card className="overflow-hidden lg:sticky lg:top-24">
      <div className="border-b border-line px-5 py-4">
        <div className="eyebrow">Your feed, right now</div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <AnimatePresence mode="popLayout">
            <m.span
              key={data?.matches ?? "…"}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28 }}
              className="tnum text-[32px] font-extrabold leading-none tracking-tight text-brand-text"
            >
              {data ? data.matches.toLocaleString("en-IN") : "—"}
            </m.span>
          </AnimatePresence>
          <span className="text-[13px] text-ink-muted">{loading ? "counting…" : "companies match"}</span>
        </div>
        <p className="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
          Counted against the same scored corpus your feed ranks over — not an illustration.
        </p>
      </div>

      <div className="p-4">
        <div className="eyebrow mb-2">Top matches today</div>
        {!data?.sample?.length ? (
          <p className="text-[12.5px] text-ink-muted">
            {sectors.length || stages.length ? "Nothing matches yet — widen the mandate." : "Pick a sector to see who shows up."}
          </p>
        ) : (
          <ul className="space-y-2">
            {data.sample.map((s: any) => (
              <m.li
                key={s.startup_id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                className="flex items-center gap-2.5"
              >
                <LogoTile name={s.legal_name} size={26} />
                <div className="min-w-0 flex-1">
                  <Link to={`/startup/${s.startup_id}`} className="block truncate text-[13px] font-bold hover:text-brand-text">
                    {s.legal_name}
                  </Link>
                  <span className="block truncate text-[11.5px] text-ink-muted">
                    {s.sector}
                    {s.hq_city ? ` · ${s.hq_city}` : ""}
                  </span>
                </div>
                {s.composite_score != null && (
                  <span className="tnum text-[13px] font-bold" style={{ color: scoreBand(s.composite_score).color }}>
                    {s.composite_score.toFixed(0)}
                  </span>
                )}
              </m.li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

/** Investor onboarding.
 *
 *  Load-bearing, not a formality: with no behavioural history the matching
 *  engine has nothing else to rank on, so these stated preferences are the
 *  entire cold-start signal. Presented as three short steps with the corpus
 *  counted live beside them, so the investor can see the mandate working
 *  before they commit to it.
 */
export default function Onboarding() {
  const navigate = useNavigate();
  const { refresh } = useInvestor();
  const { user, refresh: refreshUser } = useAuth();

  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [type, setType] = useState("angel");
  const [firm, setFirm] = useState("");
  const [sebi, setSebi] = useState("");
  const [sectors, setSectors] = useState<string[]>([]);
  const [stages, setStages] = useState<string[]>(["seed"]);
  const [geos, setGeos] = useState<string[]>([]);
  const [risk, setRisk] = useState("medium");
  const [tmin, setTmin] = useState("25000");
  const [tmax, setTmax] = useState("500000");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setName((n) => n || user.name);
      setEmail((e) => e || user.email);
    }
  }, [user]);

  const toggle = (arr: string[], set: (v: string[]) => void) => (v: string) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const canAdvance = useMemo(() => {
    if (step === 0) return name.trim().length >= 2;
    if (step === 1) return sectors.length > 0 && stages.length > 0;
    return Number(tmin) >= 0 && Number(tmax) > 0;
  }, [step, name, sectors, stages, tmin, tmax]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.setMandate({
        ticket_size_min: Number(tmin) || null,
        ticket_size_max: Number(tmax) || null,
        stage_preference: stages,
        preferred_sectors: sectors,
        geographic_preference: geos,
        risk_tolerance: risk,
      });
      await Promise.all([refreshUser(), refresh()]);
      navigate("/feed");
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
      setBusy(false);
    }
  }, [tmin, tmax, stages, sectors, geos, risk, refreshUser, refresh, navigate]);

  return (
    <div className="animate-in mx-auto max-w-5xl space-y-6">
      <div>
        <div className="eyebrow mb-1">Investor</div>
        <h1 className="text-[30px] font-extrabold leading-tight tracking-tight">Set your mandate</h1>
        <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-ink-secondary">
          Until you have interacted with enough deals for behavioural learning to kick in, this is
          the entire ranking signal — so it is worth being precise.
        </p>
      </div>

      {/* Progress rail */}
      <div className="flex flex-wrap items-center gap-2">
        {STEPS.map((s, i) => {
          const done = i < step;
          const active = i === step;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => i <= step && setStep(i)}
              className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-left transition-colors ${
                active
                  ? "border-brand bg-brand-tint"
                  : done
                    ? "border-line bg-surface hover:bg-raised"
                    : "border-line bg-plane opacity-70"
              }`}
            >
              <span
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11.5px] font-bold ${
                  active || done ? "bg-brand text-white" : "bg-raised text-ink-muted"
                }`}
              >
                {done ? "✓" : i + 1}
              </span>
              <span className="min-w-0">
                <span className={`block truncate text-[13px] font-bold ${active ? "text-brand-text" : "text-ink"}`}>
                  {s.title}
                </span>
                <span className="block truncate text-[11.5px] text-ink-muted">{s.blurb}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <Card className="p-5 sm:p-6">
          <AnimatePresence mode="wait">
            <m.div
              key={step}
              initial={{ opacity: 0, x: 18 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -18 }}
              transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
              className="space-y-4"
            >
              {step === 0 && (
                <>
                  <div className="grid gap-3.5 sm:grid-cols-2">
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-name">Name *</label>
                      <input id="inv-name" required minLength={2} className="field h-11 w-full"
                             value={name} onChange={(e) => setName(e.target.value)} />
                    </div>
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-email">Email</label>
                      <input id="inv-email" className="field h-11 w-full" value={email}
                             onChange={(e) => setEmail(e.target.value)} />
                    </div>
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-type">Type</label>
                      <select id="inv-type" className="field h-11 w-full" value={type}
                              onChange={(e) => setType(e.target.value)}>
                        <option value="angel">Angel investor</option>
                        <option value="vc_fund">VC fund</option>
                        <option value="family_office">Family office</option>
                      </select>
                    </div>
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-firm">Firm</label>
                      <input id="inv-firm" className="field h-11 w-full" placeholder="Optional"
                             value={firm} onChange={(e) => setFirm(e.target.value)} />
                    </div>
                  </div>
                  <div>
                    <label className="eyebrow mb-1.5 block" htmlFor="inv-sebi">
                      SEBI registration <span className="normal-case text-ink-muted">(marks you accredited)</span>
                    </label>
                    <input id="inv-sebi" className="field h-11 w-full tnum" placeholder="IN/AIF2/21-22/0912"
                           value={sebi} onChange={(e) => setSebi(e.target.value)} />
                    <p className="mt-1.5 text-[12px] text-ink-muted">
                      Accreditation lifts the $250,000 cap on a single marketplace offer.
                    </p>
                  </div>
                </>
              )}

              {step === 1 && (
                <>
                  <div>
                    <div className="eyebrow mb-2">Sectors *</div>
                    <Chips items={SECTORS} selected={sectors} onToggle={toggle(sectors, setSectors)} />
                  </div>
                  <div>
                    <div className="eyebrow mb-2">Stages *</div>
                    <Chips items={STAGES} selected={stages} onToggle={toggle(stages, setStages)}
                           label={(v) => STAGE_LABEL[v as Stage] ?? v} />
                  </div>
                  <div>
                    <div className="eyebrow mb-2">Geography</div>
                    <Chips items={CITIES} selected={geos} onToggle={toggle(geos, setGeos)} />
                    <p className="mt-2 text-[12px] text-ink-muted">
                      Leave empty to see companies everywhere.
                    </p>
                  </div>
                </>
              )}

              {step === 2 && (
                <>
                  <div className="grid gap-3.5 sm:grid-cols-3">
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-min">Min ticket (USD)</label>
                      <input id="inv-min" className="field h-11 w-full tnum" type="number" min={0}
                             value={tmin} onChange={(e) => setTmin(e.target.value)} />
                    </div>
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-max">Max ticket (USD)</label>
                      <input id="inv-max" className="field h-11 w-full tnum" type="number" min={0}
                             value={tmax} onChange={(e) => setTmax(e.target.value)} />
                    </div>
                    <div>
                      <label className="eyebrow mb-1.5 block" htmlFor="inv-risk">Risk tolerance</label>
                      <select id="inv-risk" className="field h-11 w-full" value={risk}
                              onChange={(e) => setRisk(e.target.value)}>
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                      </select>
                    </div>
                  </div>
                  <div className="rounded-xl bg-plane p-3.5">
                    <p className="text-[12.5px] leading-relaxed text-ink-secondary">
                      A low risk tolerance actively down-weights companies with weak runway or high
                      burn, rather than just reordering them. It changes what you are shown, not
                      only the order.
                    </p>
                  </div>
                </>
              )}
            </m.div>
          </AnimatePresence>

          {error && (
            <p className="mt-4 rounded-xl border border-critical-line bg-critical-tint px-3.5 py-2.5 text-[13px] text-critical">
              {error}
            </p>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-line pt-4">
            {step > 0 && (
              <button type="button" className="btn h-10" onClick={() => setStep(step - 1)} disabled={busy}>
                Back
              </button>
            )}
            {step < STEPS.length - 1 ? (
              <button type="button" className="btn btn-primary h-10" disabled={!canAdvance}
                      onClick={() => setStep(step + 1)}>
                Continue
              </button>
            ) : (
              <button type="button" className="btn btn-primary h-10" disabled={busy || !canAdvance}
                      onClick={save}>
                {busy ? "Saving…" : "Save mandate & view feed"}
              </button>
            )}
            {step === 1 && !sectors.length && (
              <span className="text-[12.5px] text-ink-muted">Pick at least one sector.</span>
            )}
          </div>
        </Card>

        <LivePreview sectors={sectors} stages={stages} cities={geos} />
      </div>
    </div>
  );
}
