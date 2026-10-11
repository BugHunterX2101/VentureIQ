import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AnimatePresence, m } from "motion/react";
import {
  api,
  type AgentEvent,
  type AgentTool,
  type Evidence,
  type EvidenceKind,
  type FieldStatus,
  type LedgerField,
  type OnboardFounder,
  type OnboardSnapshot,
  type RegistryCompany,
  type Stage,
} from "../lib/api";
import { STAGE_LABEL } from "../lib/format";
import { Badge, Card } from "../components/primitives";
import DocumentUpload from "../components/DocumentUpload";
import { RegistryRow, titleName, useRegistrySearch } from "../components/RegistryMatches";
import { useToast } from "../components/ui/Toast";

/** Agentic registration.
 *
 *  The founder types four things; the agent researches the rest, live, and
 *  every field ends up with a status that says how we know it. Only a live
 *  source can mark a value verified — mocked registries are shown, labelled,
 *  but never count as proof.
 */

const STAGES: Stage[] = ["idea", "seed", "series_a", "series_b_plus", "growth"];

const KIND: Record<EvidenceKind, { label: string; color: string; title: string }> = {
  network: { label: "live", color: "var(--color-live)", title: "A real request to a public source, made just now" },
  dataset: { label: "dataset", color: "var(--color-series-3)", title: "A public dataset we imported earlier — independent, but may be dated" },
  local: { label: "computed", color: "var(--color-brand)", title: "A real computation on data we already hold" },
  mock: { label: "mocked", color: "var(--color-mock)", title: "Stand-in for a consent- or fee-gated source — never proof" },
};

const STATUS: Record<FieldStatus, { label: string; tone: "good" | "brand" | "neutral" | "serious" | "warning" }> = {
  verified: { label: "Verified", tone: "good" },
  fetched: { label: "Auto-filled", tone: "brand" },
  claimed: { label: "Your input", tone: "neutral" },
  conflict: { label: "Conflict", tone: "serious" },
  disputed: { label: "Kept · flagged", tone: "serious" },
  missing: { label: "Needed", tone: "warning" },
  empty: { label: "Optional", tone: "neutral" },
};

const MONEY = new Set(["revenue", "burn_rate_monthly", "cash_balance", "mrr", "total_funding_usd"]);
// The MCA files capital in rupees, so these are shown in rupees, in the
// crore/lakh units an Indian filing is actually read in. Rendering them with a
// dollar sign would be wrong by a factor of ~85.
const INR = new Set(["paid_up_capital", "authorized_capital"]);
const NUMBER = new Set([...MONEY, ...INR, "active_users", "employee_count", "founded_year"]);

function fmtInr(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
  return `₹${v.toLocaleString("en-IN")}`;
}

function fmtValue(key: string, v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (MONEY.has(key)) return `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (INR.has(key)) return fmtInr(Number(v));
  if (key === "stage") return STAGE_LABEL[v] ?? String(v);
  if (key === "active_users" || key === "employee_count") return Number(v).toLocaleString("en-US");
  return String(v);
}

function KindDot({ kind }: { kind: EvidenceKind }) {
  return (
    <span
      title={KIND[kind].title}
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{ background: KIND[kind].color }}
    />
  );
}

function KindTag({ kind }: { kind: EvidenceKind }) {
  return (
    <span title={KIND[kind].title} className="inline-flex items-center gap-1 text-[11px] font-semibold text-ink-muted">
      <KindDot kind={kind} />
      {KIND[kind].label}
    </span>
  );
}

function Spin({ className = "" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="var(--color-brand)" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/* ═══════════════════════════════ page ═══════════════════════════════════ */

export default function Register() {
  const [params, setParams] = useSearchParams();
  const sid = params.get("s");
  return sid ? (
    <Workspace key={sid} sid={sid} onRestart={() => setParams({})} />
  ) : (
    <StartForm
      onStarted={(id) => setParams({ s: id })}
      prefill={{ cin: params.get("cin") ?? "", name: params.get("name") ?? "" }}
    />
  );
}

/* ═════════════════════════════ start form ═══════════════════════════════ */

function StartForm({
  onStarted,
  prefill,
}: {
  onStarted: (id: string) => void;
  prefill: { cin: string; name: string };
}) {
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [noSite, setNoSite] = useState(false);
  const [india, setIndia] = useState(!!prefill.cin);
  const [claimed, setClaimed] = useState<{ cin: string; name: string } | null>(prefill.cin ? prefill : null);
  const [stage, setStage] = useState<Stage>("seed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [f, setF] = useState({
    website: "",
    legal_name: prefill.name,
    founder_name: "",
    email: "",
    cin: prefill.cin,
    gstin: "",
    gst_consent: false,
  });
  const pick = (c: RegistryCompany) => {
    setF((p) => ({ ...p, cin: c.cin, legal_name: titleName(c.name) }));
    setClaimed({ cin: c.cin, name: titleName(c.name) });
  };

  useEffect(() => {
    api.onboardTools().then((r) => setTools(r.tools)).catch(() => {});
  }, []);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function start(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.onboardStart({
        website: noSite ? null : f.website,
        // A company picked from the registry keeps its name as a claim to check.
        legal_name: noSite || claimed ? f.legal_name : null,
        founder_name: f.founder_name,
        email: f.email,
        stage,
        cin: india ? f.cin : null,
        gstin: india ? f.gstin : null,
        gst_consent: india && f.gst_consent,
      });
      onStarted(r.session_id);
    } catch (err) {
      setError(String((err as Error).message));
      setBusy(false);
    }
  }

  const groups: [EvidenceKind, string][] = [
    ["network", "Live lookups"],
    ["dataset", "Public datasets"],
    ["local", "Computed here"],
    ["mock", "Mocked until licensed"],
  ];

  return (
    <div className="animate-in grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
      <Card className="p-6 sm:p-8">
        <div className="eyebrow mb-2">Register a startup</div>
        <h1 className="text-[28px] font-extrabold leading-tight tracking-tight sm:text-[32px]">
          Four fields. Our agent finds the rest.
        </h1>
        <p className="mt-2 max-w-[600px] text-[15px] leading-relaxed text-ink-secondary">
          Give us your website and we'll research your company in public sources, fill in the profile,
          and show you exactly what we could verify — and what we couldn't.
        </p>

        <form onSubmit={start} className="mt-7 space-y-5">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label htmlFor="website" className="text-[13.5px] font-bold">
                {noSite ? "Company name" : "Company website"}
              </label>
              <button type="button" className="text-[12.5px] font-semibold text-brand-text hover:underline" onClick={() => setNoSite((v) => !v)}>
                {noSite ? "I have a website" : "No website yet?"}
              </button>
            </div>
            {noSite ? (
              <input id="website" className="field h-11 w-full" required minLength={2} value={f.legal_name} onChange={set("legal_name")} placeholder="Acme Robotics" />
            ) : (
              <input id="website" className="field h-11 w-full" required value={f.website} onChange={set("website")} placeholder="acme.com" inputMode="url" autoComplete="url" />
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="name" className="mb-1.5 block text-[13.5px] font-bold">Your name</label>
              <input id="name" className="field h-11 w-full" required minLength={2} value={f.founder_name} onChange={set("founder_name")} autoComplete="name" />
            </div>
            <div>
              <label htmlFor="email" className="mb-1.5 block text-[13.5px] font-bold">Work email</label>
              <input id="email" type="email" className="field h-11 w-full" required value={f.email} onChange={set("email")} placeholder="you@acme.com" autoComplete="email" />
            </div>
          </div>

          <fieldset>
            <legend className="mb-1.5 text-[13.5px] font-bold">Stage</legend>
            <div className="flex flex-wrap gap-2">
              {STAGES.map((st) => (
                <button
                  key={st}
                  type="button"
                  aria-pressed={stage === st}
                  onClick={() => setStage(st)}
                  className={`relative isolate rounded-full border px-3.5 py-2 text-[13px] font-semibold transition-colors ${
                    stage === st ? "border-brand text-brand-text" : "border-line-strong text-ink-secondary hover:border-ink-disabled"
                  }`}
                >
                  {stage === st && (
                    <m.span layoutId="reg-stage" className="absolute inset-0 -z-10 rounded-full bg-brand-tint" transition={{ type: "spring", stiffness: 500, damping: 38 }} />
                  )}
                  {STAGE_LABEL[st]}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[12.5px] text-ink-muted">
              {stage === "idea" ? "Idea stage: we won't ask for financials." : "You'll be asked for burn and cash later — no public source has them."}
            </p>
          </fieldset>

          <div className="rounded-xl border border-line">
            <button type="button" onClick={() => setIndia((v) => !v)} aria-expanded={india} className="flex w-full items-center gap-2 px-4 py-3 text-left text-[13.5px] font-bold">
              <m.svg animate={{ rotate: india ? 90 : 0 }} width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
              </m.svg>
              Registered in India? <span className="font-medium text-ink-muted">Optional — unlocks registry checks</span>
            </button>
            <AnimatePresence initial={false}>
              {india && (
                <m.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <div className="grid gap-4 border-t border-line px-4 py-4 sm:grid-cols-2">
                    <RegistryFinder claimed={claimed} onPick={pick} onClear={() => setClaimed(null)} />
                    <div>
                      <label htmlFor="cin" className="mb-1.5 block text-[13px] font-bold">CIN</label>
                      <input id="cin" className="field tnum h-10 w-full uppercase" value={f.cin} onChange={set("cin")} placeholder="U72900KA2019PTC123456" maxLength={25} />
                    </div>
                    <div>
                      <label htmlFor="gstin" className="mb-1.5 block text-[13px] font-bold">GSTIN</label>
                      <input id="gstin" className="field tnum h-10 w-full uppercase" value={f.gstin} onChange={set("gstin")} placeholder="29ABCDE1234F1Z5" maxLength={18} />
                    </div>
                    <label className="flex items-start gap-2.5 text-[13px] leading-snug text-ink-secondary sm:col-span-2">
                      <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--color-brand)]" checked={f.gst_consent} onChange={set("gst_consent")} />
                      <span>
                        I consent to VentureIQ pulling my GST filing summary to cross-check the revenue I report.
                        <span className="text-ink-muted"> In this build the GST pull is simulated and labelled as such.</span>
                      </span>
                    </label>
                  </div>
                </m.div>
              )}
            </AnimatePresence>
          </div>

          {error && (
            <div role="alert" className="rounded-xl border border-critical-line bg-critical-tint px-4 py-3 text-[13.5px] text-critical-text">
              {error}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-4">
            <button className="btn btn-primary h-12 rounded-xl px-6 text-[15px]" disabled={busy}>
              {busy ? <Spin /> : null}
              {busy ? "Starting…" : "Research my company"}
            </button>
            <Link to="/submit" className="text-[13.5px] font-semibold text-ink-secondary hover:text-ink">
              Prefer to fill everything in yourself?
            </Link>
          </div>
        </form>
      </Card>

      <Card className="p-6">
        <div className="eyebrow mb-1">How the agent searches</div>
        <p className="mb-4 text-[13.5px] leading-relaxed text-ink-secondary">
          The agent picks sources based on what it finds — a GitHub link on your site gets confirmed; an
          Indian address unlocks the MCA company registry; nothing gated is touched without your consent.
        </p>
        {groups.map(([kind, title]) => (
          <div key={kind} className="mb-4 last:mb-0">
            <div className="mb-2 flex items-center gap-2 text-[12.5px] font-bold uppercase tracking-[0.06em] text-ink-muted">
              <KindDot kind={kind} /> {title}
            </div>
            <ul className="space-y-1">
              {tools.filter((t) => t.kind === kind).map((t) => (
                <li key={t.id}>
                  <details className="group rounded-lg px-2 py-1.5 transition-colors open:bg-raised hover:bg-raised">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-[13.5px] font-semibold">
                      {t.label}
                      <svg className="shrink-0 text-ink-muted transition-transform group-open:rotate-90" width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
                        <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
                      </svg>
                    </summary>
                    <div className="mt-1.5 space-y-1 text-[12.5px] leading-relaxed text-ink-secondary">
                      <p><b className="text-ink">Finds:</b> {t.what}</p>
                      <p><b className="text-ink">How:</b> {t.how}</p>
                      <p><b className="text-ink">Access:</b> {t.consent}</p>
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Card>
    </div>
  );
}

function RegistryFinder({
  claimed,
  onPick,
  onClear,
}: {
  claimed: { cin: string; name: string } | null;
  onPick: (c: RegistryCompany) => void;
  onClear: () => void;
}) {
  const [q, setQ] = useState("");
  const { items, meta, loading } = useRegistrySearch(q, 5);
  if (claimed)
    return (
      <div className="flex items-center gap-3 rounded-lg border border-good-line bg-good-tint px-3 py-2.5 text-[13px] sm:col-span-2">
        <span className="min-w-0 flex-1 text-good-text">
          Registering <b>{claimed.name}</b> <span className="tnum">({claimed.cin})</span> from the MCA registry.
        </span>
        <button type="button" className="shrink-0 text-[12.5px] font-semibold text-brand-text hover:underline" onClick={onClear}>
          Change
        </button>
      </div>
    );
  return (
    <div className="sm:col-span-2">
      <label htmlFor="registry-q" className="mb-1.5 block text-[13px] font-bold">
        Find your company in the MCA registry
      </label>
      <div className="relative">
        <input
          id="registry-q"
          className="field h-10 w-full"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Registered name or CIN"
          autoComplete="off"
        />
        {loading && <Spin className="absolute right-3 top-3" />}
      </div>
      {items.length > 0 && (
        <div className="mt-2 divide-y divide-grid overflow-hidden rounded-lg border border-line">
          {items.map((c) => (
            <RegistryRow
              key={c.cin}
              c={c}
              action={
                c.startup_id ? (
                  <Link to={`/startup/${c.startup_id}`} className="btn h-8 px-3 text-[12px]">Already listed</Link>
                ) : (
                  <button type="button" className="btn btn-primary h-8 px-3 text-[12px]" onClick={() => onPick(c)}>
                    This is us
                  </button>
                )
              }
            />
          ))}
        </div>
      )}
      <p className="mt-1.5 text-[12px] text-ink-muted">
        {meta && !meta.complete
          ? `Name search covers ${meta.companies.toLocaleString("en-IN")} imported companies so far; an exact CIN is always checked live.`
          : "Picking your company fills in the CIN. Not listed? Enter it below, or skip — you can still register."}
      </p>
    </div>
  );
}

function RegistryCandidates({ items, onPick, busy }: { items: RegistryCompany[]; onPick: (cin: string) => void; busy: boolean }) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-[17px] font-bold">Which registered company is yours?</h2>
        <p className="text-[12.5px] text-ink-muted">
          Several companies in the MCA registry match your name. Pick yours and we'll check it against what we found — or
          skip if none are you.
        </p>
      </div>
      <div className="divide-y divide-grid">
        {items.map((c) => (
          <RegistryRow
            key={c.cin}
            c={c}
            action={
              <button className="btn h-8 px-3 text-[12.5px]" disabled={busy} onClick={() => onPick(c.cin)}>
                This is us
              </button>
            }
          />
        ))}
      </div>
    </Card>
  );
}

/* ══════════════════════════════ workspace ═══════════════════════════════ */

interface TraceStep {
  kind: "step";
  id: string;
  label: string;
  tool: string;
  source: EvidenceKind;
  reason: string;
  status: "queued" | "running" | "ok" | "failed";
  summary?: string;
  ms?: number;
  findings: { field: string; value: any; label: string }[];
}
type TraceItem = TraceStep | { kind: "thought"; seq: number; text: string };

function buildTrace(events: AgentEvent[]): TraceItem[] {
  const items: TraceItem[] = [];
  const steps = new Map<string, TraceStep>();
  for (const e of events) {
    if (e.type === "thought") items.push({ kind: "thought", seq: e.seq, text: e.text });
    else if (e.type === "plan") {
      const s: TraceStep = { kind: "step", id: e.id, label: e.label, tool: e.tool, source: e.kind, reason: e.reason, status: "queued", findings: [] };
      steps.set(e.id, s);
      items.push(s);
    } else if (e.type === "step") {
      const s = steps.get(e.id);
      if (s) s.status = "running";
    } else if (e.type === "step_done") {
      const s = steps.get(e.id);
      if (s) Object.assign(s, { status: e.ok ? "ok" : "failed", summary: e.summary, ms: e.ms });
    } else if (e.type === "finding" && e.tool) {
      steps.get(e.tool)?.findings.push({ field: e.field, value: e.value, label: e.label });
    }
  }
  return items;
}

function Workspace({ sid, onRestart }: { sid: string; onRestart: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [snap, setSnap] = useState<OnboardSnapshot | null>(null);
  const [lost, setLost] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [now, setNow] = useState(() => performance.now());
  const startedAt = useRef(performance.now());

  useEffect(() => {
    let final = false;
    const close = api.onboardEvents(sid, {
      onEvent: (e) => setEvents((prev) => (prev.some((p) => p.seq === e.seq) ? prev : [...prev, e])),
      onState: setSnap,
      onSnapshot: (s) => {
        final = true;
        setSnap(s);
      },
      onError: () => {
        if (!final) api.onboardSnapshot(sid).then(setSnap).catch(() => setLost(true));
      },
    });
    api.sectors().then((r) => setSectors(r.filter((x) => x.count >= 20).map((x) => x.sector))).catch(() => {});
    return close;
  }, [sid]);

  const running = !snap || snap.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(t);
  }, [running]);

  const trace = useMemo(() => buildTrace(events), [events]);
  const steps = trace.filter((t): t is TraceStep => t.kind === "step");
  const done = steps.filter((s) => s.status === "ok" || s.status === "failed").length;
  const lastT = events.length ? events[events.length - 1].t : 0;

  async function edit(key: string, value?: unknown, resolution?: "accept" | "keep") {
    setBusyKey(key);
    setError(null);
    try {
      setSnap(await api.onboardEdit(sid, [{ key, value, resolution }]));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyKey(null);
    }
  }

  async function saveFounders(list: Omit<OnboardFounder, "source" | "check">[]) {
    try {
      setSnap(await api.onboardFounders(sid, list));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function checkFounder(i: number) {
    setBusyKey(`founder-${i}`);
    try {
      setSnap(await api.onboardCheckFounder(sid, i));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyKey(null);
    }
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const r = await api.onboardSubmit(sid);
      toast({ title: "Profile created", body: "Scores were computed from the verified evidence.", tone: "good" });
      navigate(`/startup/${r.startup_id}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  }

  if (lost)
    return (
      <Card className="p-8 text-center">
        <div className="text-[18px] font-bold">This registration session couldn't be found.</div>
        <button className="btn btn-primary mt-4" onClick={onRestart}>Start again</button>
      </Card>
    );

  const counts = snap?.ledger.counts ?? {};
  const blocking = snap?.ledger.blocking ?? [];
  const fieldLabel = (k: string) => (k === "founders" ? "Founders" : snap?.ledger.fields.find((f) => f.key === k)?.label ?? k);
  const elapsed = running ? (now - startedAt.current) / 1000 : lastT / 1000;

  return (
    <div className="animate-in space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow mb-1">Register a startup</div>
          <h1 className="text-[26px] font-extrabold leading-tight tracking-tight sm:text-[28px]">
            {running ? "Researching " : "Review "}
            <span className="text-brand-text">{snap?.facts.domain ?? snap?.inputs.legal_name ?? "your company"}</span>
          </h1>
          <p className="mt-1 text-[14px] text-ink-secondary">
            {running
              ? "Watch the agent work. Fields fill in as sources answer."
              : "Confirm what we found, resolve conflicts, and add what no public source has."}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5" aria-live="polite">
          {(["verified", "fetched", "claimed", "conflict", "missing"] as FieldStatus[]).map((k) =>
            counts[k] ? (
              <Badge key={k} tone={STATUS[k].tone}>
                {counts[k]} {STATUS[k].label.toLowerCase()}
              </Badge>
            ) : null,
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="order-2 min-w-0 space-y-5 lg:order-1">
          {snap?.facts.duplicate_of && (
            <div className="rounded-xl border border-critical-line bg-critical-tint px-4 py-3 text-[13.5px] text-critical-text">
              This website already belongs to a{" "}
              <Link className="font-bold underline" to={`/startup/${snap.facts.duplicate_of}`}>VentureIQ profile</Link>. Submitting again will be flagged for review.
            </div>
          )}
          {!snap ? (
            <Card className="p-5"><div className="skeleton h-[360px]" /></Card>
          ) : (
            <>
              {!running && snap.facts.registry_candidates?.length > 0 && !snap.facts.registry && (
                <RegistryCandidates items={snap.facts.registry_candidates} busy={busyKey === "cin"} onPick={(cin) => edit("cin", cin)} />
              )}
              {(["Company", "Registry", "Presence", "Financials"] as const).map((g) => (
                <FieldGroup
                  key={g}
                  title={g}
                  fields={snap.ledger.fields.filter((f) => f.group === g)}
                  running={running}
                  busyKey={busyKey}
                  sectors={sectors}
                  onEdit={edit}
                  gstLinked={g === "Financials" && !!snap.facts.gst_turnover_factor}
                />
              ))}
              <DocumentUpload
                sessionId={sid}
                onDone={(r) => {
                  if (r.snapshot) setSnap(r.snapshot);
                  const conflicts = r.checks.filter((c) => c.status === "conflict").length;
                  toast({
                    title: `${r.doc_type_label} read`,
                    body: conflicts
                      ? `${conflicts} thing${conflicts > 1 ? "s" : ""} to resolve — see the document card.`
                      : `${r.fields.length} field(s) taken from it.`,
                    tone: conflicts ? "warning" : "good",
                  });
                }}
              />
              <Founders
                founders={snap.founders}
                busyKey={busyKey}
                onSave={saveFounders}
                onCheck={checkFounder}
                needed={blocking.includes("founders")}
              />
            </>
          )}
        </div>

        <aside className="order-1 lg:sticky lg:top-[calc(var(--header-h)+20px)] lg:order-2">
          <Card className="overflow-hidden" lit={false}>
            <div className="border-b border-line px-5 py-4">
              <div className="flex items-center gap-2">
                {running ? <span className="pulse-ring h-2.5 w-2.5 rounded-full bg-live" /> : <span className="h-2.5 w-2.5 rounded-full bg-good" />}
                <span className="text-[15px] font-bold">Agent trace</span>
                <span className="tnum ml-auto text-[12.5px] text-ink-muted">
                  {done}/{steps.length} sources · {elapsed.toFixed(1)}s
                </span>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-track">
                <m.div className="h-full rounded-full bg-brand" animate={{ width: `${steps.length ? (done / steps.length) * 100 : 4}%` }} transition={{ type: "spring", stiffness: 120, damping: 22 }} />
              </div>
              <div className="mt-2.5 flex flex-wrap gap-3">
                {(Object.keys(KIND) as EvidenceKind[]).map((k) => <KindTag key={k} kind={k} />)}
              </div>
            </div>
            <ol className="max-h-[42vh] space-y-1 lg:max-h-[70vh] overflow-y-auto px-3 py-3" aria-label="Agent steps">
              <AnimatePresence initial={false}>
                {trace.map((item) =>
                  item.kind === "thought" ? (
                    <m.li key={`t${item.seq}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2 px-2 py-1.5 text-[12.5px] italic leading-snug text-ink-secondary">
                      <svg className="mt-0.5 shrink-0 text-brand-text" width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden>
                        <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                      {item.text}
                    </m.li>
                  ) : (
                    <TraceRow key={item.id} step={item} />
                  ),
                )}
              </AnimatePresence>
              {!events.length && (
                <li className="flex items-center gap-2 px-2 py-3 text-[13px] text-ink-muted"><Spin /> Connecting…</li>
              )}
            </ol>
          </Card>
        </aside>
      </div>

      {/* submit bar */}
      <div className="sticky bottom-3 z-30 rounded-2xl border border-line-strong bg-header shadow-[var(--shadow-pop)] backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-5">
          <div className="min-w-0 basis-full text-[13px] sm:flex-1 sm:basis-auto sm:text-[13.5px]">
            {error ? (
              <span className="text-critical-text">{error}</span>
            ) : running ? (
              <span className="text-ink-secondary">The agent is still researching…</span>
            ) : blocking.length ? (
              <span className="text-ink-secondary">
                <b className="text-ink">{blocking.length} to resolve:</b>{" "}
                {blocking.map((k, i) => (
                  <span key={k}>
                    {i > 0 && ", "}
                    <a href={`#field-${k}`} className="font-semibold text-brand-text hover:underline">{fieldLabel(k)}</a>
                  </span>
                ))}
              </span>
            ) : (
              <span className="text-good-text">Everything's resolved. Mocked checks stay labelled on your profile.</span>
            )}
          </div>
          <button className="btn ml-auto h-10 sm:ml-0" onClick={onRestart} disabled={submitting}>Start over</button>
          <button className="btn btn-primary h-10 px-5" disabled={running || blocking.length > 0 || submitting} onClick={submit}>
            {submitting && <Spin />}
            {submitting ? "Scoring…" : "Create profile"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────── trace row ─────────────────────────────── */

function TraceRow({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const icon =
    step.status === "running" ? (
      <Spin />
    ) : step.status === "ok" ? (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-label="done"><path d="M5 12l4.5 4.5L19 7" stroke="var(--color-good)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
    ) : step.status === "failed" ? (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-label="failed"><path d="M6 6l12 12M18 6L6 18" stroke="var(--color-serious)" strokeWidth="3" strokeLinecap="round" /></svg>
    ) : (
      <span className="block h-3 w-3 rounded-full border-2 border-line-strong" aria-label="queued" />
    );

  return (
    <m.li layout initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} className={`rounded-xl px-2 py-2 transition-colors ${step.status === "running" ? "bg-brand-tint" : ""}`}>
      <button type="button" className="flex w-full items-start gap-2.5 text-left" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-[13.5px] font-bold">{step.label}</span>
            <KindTag kind={step.source} />
            {step.ms !== undefined && <span className="tnum ml-auto text-[11.5px] text-ink-muted">{step.ms}ms</span>}
          </span>
          <span className="mt-0.5 block text-[12.5px] leading-snug text-ink-muted">{step.status === "queued" || step.status === "running" ? step.reason : step.summary}</span>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <m.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="ml-[26px] mt-1.5 space-y-1 border-l-2 border-line pl-3 text-[12px]">
              <div className="text-ink-secondary"><b className="text-ink">Why:</b> {step.reason}</div>
              {step.findings.length ? (
                step.findings.map((f, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="shrink-0 text-ink-muted">{f.field.replace(/_/g, " ")}</span>
                    <span className="truncate font-semibold">{fmtValue(f.field, f.value)}</span>
                  </div>
                ))
              ) : (
                <div className="text-ink-muted">No field-level findings.</div>
              )}
            </div>
          </m.div>
        )}
      </AnimatePresence>
      {!open && step.findings.length > 0 && (
        <div className="ml-[26px] mt-1 text-[11.5px] font-semibold text-brand-text">+{step.findings.length} finding{step.findings.length > 1 ? "s" : ""}</div>
      )}
    </m.li>
  );
}

/* ─────────────────────────────── ledger ────────────────────────────────── */

function FieldGroup({
  title,
  fields,
  running,
  busyKey,
  sectors,
  onEdit,
  gstLinked,
}: {
  title: string;
  fields: LedgerField[];
  running: boolean;
  busyKey: string | null;
  sectors: string[];
  onEdit: (key: string, value?: unknown, resolution?: "accept" | "keep") => void;
  gstLinked: boolean;
}) {
  const [showOptional, setShowOptional] = useState(false);
  const shown = fields.filter((f) => f.status !== "empty" || (title === "Financials" && !f.readonly));
  const optional = fields.filter((f) => !shown.includes(f) && !f.readonly);
  if (!shown.length && !optional.length) return null;

  const blurb: Record<string, string> = {
    Company: "Who you are. Most of this should come from public sources.",
    Registry: "Identifiers and domain facts that are hard to fake.",
    Presence: "Where you show up publicly.",
    Financials: gstLinked
      ? "Only you know these. Revenue is reconciled against your GST filings (simulated pull)."
      : "Only you know these. They're marked as your input.",
  };

  return (
    <Card className="p-0">
      <div className="flex items-baseline justify-between gap-3 px-5 pt-4">
        <div>
          <h2 className="text-[17px] font-bold">{title}</h2>
          <p className="text-[12.5px] text-ink-muted">{blurb[title]}</p>
        </div>
      </div>
      <div className="mt-2 divide-y divide-grid">
        {shown.map((f) => (
          <FieldRow key={f.key} f={f} running={running} busy={busyKey === f.key} sectors={sectors} onEdit={onEdit} />
        ))}
        {showOptional && optional.map((f) => (
          <FieldRow key={f.key} f={f} running={running} busy={busyKey === f.key} sectors={sectors} onEdit={onEdit} />
        ))}
      </div>
      {optional.length > 0 && (
        <button className="w-full border-t border-grid px-5 py-2.5 text-left text-[12.5px] font-semibold text-brand-text hover:bg-row-hover" onClick={() => setShowOptional((v) => !v)}>
          {showOptional ? "Hide optional fields" : `Add optional fields (${optional.map((o) => o.label).join(", ")})`}
        </button>
      )}
    </Card>
  );
}

function Editor({
  f,
  sectors,
  onDone,
}: {
  f: LedgerField;
  sectors: string[];
  onDone: (v: unknown | undefined) => void;
}) {
  const [v, setV] = useState(f.value === null || f.value === undefined ? "" : String(f.value));
  const commit = () => {
    if (v === String(f.value ?? "")) return onDone(undefined);
    onDone(NUMBER.has(f.key) ? (v === "" ? null : Number(v)) : v.trim() || null);
  };
  const common = {
    autoFocus: true,
    onBlur: commit,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !(e.target instanceof HTMLTextAreaElement)) commit();
      if (e.key === "Escape") onDone(undefined);
    },
    "aria-label": f.label,
  };
  // A dropdown commits as soon as you choose: waiting for a blur reads as broken.
  if (f.key === "stage")
    return (
      <select className="field h-9 w-full max-w-[260px]" value={v} onChange={(e) => onDone(e.target.value)} {...common} onBlur={undefined}>
        {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
      </select>
    );
  if (f.key === "sector")
    return (
      <select
        className="field h-9 w-full max-w-[260px]"
        value={v}
        onChange={(e) => (e.target.value ? onDone(e.target.value) : setV(""))}
        {...common}
        onBlur={undefined}
      >
        {!v && <option value="">Choose a sector</option>}
        {[...new Set([...(v ? [v] : []), ...sectors])].map((s) => <option key={s}>{s}</option>)}
      </select>
    );
  if (f.key === "long_description")
    return <textarea className="field min-h-[110px] w-full py-2" value={v} onChange={(e) => setV(e.target.value)} {...common} />;
  return (
    <input
      className="field h-9 w-full max-w-[420px]"
      type={NUMBER.has(f.key) ? "number" : "text"}
      min={NUMBER.has(f.key) ? 0 : undefined}
      value={v}
      onChange={(e) => setV(e.target.value)}
      {...common}
    />
  );
}

function FieldRow({
  f,
  running,
  busy,
  sectors,
  onEdit,
}: {
  f: LedgerField;
  running: boolean;
  busy: boolean;
  sectors: string[];
  onEdit: (key: string, value?: unknown, resolution?: "accept" | "keep") => void;
}) {
  const [editing, setEditing] = useState(false);
  const [showEv, setShowEv] = useState(f.status === "conflict");
  const st = STATUS[f.status];
  const canEdit = !f.readonly && !running;
  const sources = f.evidence.filter((e) => e.value !== null || e.note);

  // Flash when a value arrives or changes while the agent is running.
  const prev = useRef(f.value);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (prev.current !== f.value) {
      prev.current = f.value;
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 900);
      return () => clearTimeout(t);
    }
  }, [f.value]);

  return (
    <m.div
      layout="position"
      id={`field-${f.key}`}
      className={`scroll-mt-24 px-5 py-3 transition-colors duration-700 ${flash ? "bg-brand-tint" : ""} ${
        f.status === "conflict" ? "bg-serious-tint/40" : f.status === "missing" ? "bg-warning-tint/40" : ""
      }`}
    >
      <div className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[170px_minmax(0,1fr)_auto] sm:items-start">
        <div className="pt-1 text-[13px] font-semibold text-ink-secondary">
          {f.label}
          {f.required && <span className="text-serious" aria-label="required"> *</span>}
        </div>

        <div className="min-w-0">
          {editing ? (
            <Editor
              f={f}
              sectors={sectors}
              onDone={(v) => {
                setEditing(false);
                if (v !== undefined) onEdit(f.key, v);
              }}
            />
          ) : (
            <div className="flex min-w-0 items-start gap-2">
              <span
                className={`min-w-0 break-words pt-0.5 text-[14px] ${f.value === null ? "text-ink-muted" : "font-semibold"} ${
                  f.key === "long_description" ? "line-clamp-3 font-normal" : ""
                }`}
              >
                {f.key === "website" && f.value ? (
                  <a href={f.value} target="_blank" rel="noreferrer noopener" className="text-brand-text hover:underline">{f.value}</a>
                ) : f.value === null && running && !f.founder_only ? (
                  <span className="inline-flex items-center gap-1.5 text-ink-muted"><Spin /> looking…</span>
                ) : (
                  fmtValue(f.key, f.value)
                )}
              </span>
              {canEdit && (
                <button className="shrink-0 rounded-md px-1.5 py-0.5 text-[12px] font-semibold text-brand-text hover:bg-brand-tint" onClick={() => setEditing(true)}>
                  {f.value === null ? "Add" : "Edit"}
                </button>
              )}
              {busy && <Spin className="mt-1" />}
            </div>
          )}
          {(f.note || f.hint) && (
            <div className={`mt-0.5 flex items-start gap-1.5 text-[12px] leading-snug ${f.warn ? "text-warning-text" : "text-ink-muted"}`}>
              {f.warn && (
                <svg className="mt-px shrink-0" width="12" height="12" viewBox="0 0 24 24" fill="none" aria-label="warning"><path d="M12 4l9 16H3l9-16z" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /></svg>
              )}
              {f.note || f.hint}
            </div>
          )}
          {f.status === "conflict" && !running && (
            <div className="mt-2 flex flex-wrap gap-2">
              {f.suggestion && (
                <button className="btn btn-primary h-8 px-3 text-[12.5px]" onClick={() => onEdit(f.key, undefined, "accept")}>
                  Use “{fmtValue(f.key, f.suggestion.value).slice(0, 40)}”
                </button>
              )}
              {f.value !== null && (
                <button className="btn h-8 px-3 text-[12.5px]" onClick={() => onEdit(f.key, undefined, "keep")} title="Your value is kept and the disagreement is flagged for review">
                  Keep mine (flag for review)
                </button>
              )}
              <button className="btn h-8 px-3 text-[12.5px]" onClick={() => setEditing(true)}>Edit</button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 sm:flex-col sm:items-end">
          {f.status !== "empty" && <Badge tone={st.tone}>{st.label}</Badge>}
          {sources.length > 0 && (
            <button className="text-[12px] font-semibold text-ink-muted hover:text-ink" onClick={() => setShowEv((v) => !v)} aria-expanded={showEv}>
              {sources.length} source{sources.length > 1 ? "s" : ""} {showEv ? "▴" : "▾"}
            </button>
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {showEv && sources.length > 0 && (
          <m.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden sm:ml-[186px]">
            <ul className="mt-2 space-y-1 rounded-lg border border-line bg-raised p-2">
              {sources.map((e, i) => (
                <EvidenceRow key={i} e={e} fieldKey={f.key} canUse={canEdit && e.suggest && e.value !== null && String(e.value) !== String(f.value)} onUse={() => onEdit(f.key, e.value)} />
              ))}
            </ul>
          </m.div>
        )}
      </AnimatePresence>
    </m.div>
  );
}

function EvidenceRow({ e, fieldKey, canUse, onUse }: { e: Evidence; fieldKey: string; canUse: boolean; onUse: () => void }) {
  const verdict: Record<string, ReactNode> = {
    agree: <span className="font-bold text-good-text" title="Agrees">✓</span>,
    disagree: <span className="font-bold text-serious" title="Disagrees">✕</span>,
    picked: <span className="text-[10px] font-bold uppercase text-brand-text" title="This is the value shown">used</span>,
    neutral: <span className="text-ink-muted" title="Not comparable">–</span>,
  };
  return (
    <li className="flex items-start gap-2 rounded-md px-1.5 py-1 text-[12.5px]">
      <span className="mt-1"><KindDot kind={e.kind} /></span>
      <span className="w-7 shrink-0 text-center leading-5">{e.verdict ? verdict[e.verdict] : null}</span>
      <span className="min-w-0 flex-1">
        <span className="font-semibold">{e.label}</span>
        {e.value !== null && e.value !== undefined && (
          <span className="text-ink-secondary"> · <span className="break-words">{fmtValue(fieldKey, e.value).slice(0, 160)}</span></span>
        )}
        {e.note && <span className="block text-[11.5px] text-ink-muted">{e.note}</span>}
      </span>
      {canUse && (
        <button className="shrink-0 rounded-md px-1.5 py-0.5 text-[12px] font-semibold text-brand-text hover:bg-brand-tint" onClick={onUse}>
          Use
        </button>
      )}
    </li>
  );
}

/* ─────────────────────────────── founders ──────────────────────────────── */

type FounderDraft = Omit<OnboardFounder, "source" | "check">;

function Founders({
  founders,
  busyKey,
  onSave,
  onCheck,
  needed,
}: {
  founders: OnboardFounder[];
  busyKey: string | null;
  onSave: (list: FounderDraft[]) => void;
  onCheck: (i: number) => void;
  needed: boolean;
}) {
  const [draft, setDraft] = useState<FounderDraft[]>([]);
  const key = founders.map((f) => `${f.name}|${f.role}|${f.github}|${f.linkedin}`).join(";");
  useEffect(() => {
    setDraft(founders.map(({ name, role, github, linkedin }) => ({ name, role, github, linkedin })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const update = (i: number, k: keyof FounderDraft, v: string) =>
    setDraft((d) => d.map((f, j) => (j === i ? { ...f, [k]: v || null } : f)));
  const commit = (list = draft) => {
    const clean = list.filter((f) => f.name?.trim());
    const same = JSON.stringify(clean) === JSON.stringify(founders.map(({ name, role, github, linkedin }) => ({ name, role, github, linkedin })));
    if (!same) onSave(clean);
  };

  return (
    <Card className="p-0" id="field-founders">
      <div className="flex items-baseline justify-between gap-3 px-5 pt-4">
        <div>
          <h2 className="text-[17px] font-bold">Founders {needed && <span className="text-serious">*</span>}</h2>
          <p className="text-[12.5px] text-ink-muted">
            Names found on your site are pre-filled. Add a GitHub handle or LinkedIn URL and we'll check both live: does the profile exist, is it the right person, and does it list this company?
          </p>
        </div>
      </div>
      <div className="mt-2 divide-y divide-grid">
        {draft.map((f, i) => {
          const orig = founders[i];
          const check = orig?.check;
          return (
            <div key={i} className="grid grid-cols-1 gap-2 px-5 py-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center">
              <input className="field h-9" aria-label="Founder name" placeholder="Full name" value={f.name ?? ""} onChange={(e) => update(i, "name", e.target.value)} onBlur={() => commit()} />
              <input className="field h-9" aria-label="Role" placeholder="Role" value={f.role ?? ""} onChange={(e) => update(i, "role", e.target.value)} onBlur={() => commit()} />
              <input className="field h-9 sm:col-span-2" aria-label="LinkedIn profile URL" placeholder="linkedin.com/in/…" value={f.linkedin ?? ""} onChange={(e) => update(i, "linkedin", e.target.value)} onBlur={() => commit()} />
              <div className="flex gap-1.5">
                <input className="field h-9 min-w-0 flex-1" aria-label="GitHub handle" placeholder="GitHub handle" value={f.github ?? ""} onChange={(e) => update(i, "github", e.target.value)} onBlur={() => commit()} />
                {((orig?.github && orig.github === f.github) || (orig?.linkedin && orig.linkedin === f.linkedin)) && (
                  <button className="btn h-9 px-2.5 text-[12px]" onClick={() => onCheck(i)} disabled={busyKey === `founder-${i}`}>
                    {busyKey === `founder-${i}` ? <Spin /> : "Check"}
                  </button>
                )}
              </div>
              <div className="flex items-center justify-end gap-2">
                {orig?.source === "website" && <Badge tone="brand">From your site</Badge>}
                {(orig?.checks ?? (check ? [{ ...check, label: "Profile" }] : [])).map((c) => (
                  <Badge key={c.label} tone={STATUS[c.status].tone}>
                    {c.label}: {STATUS[c.status].label.toLowerCase()}
                  </Badge>
                ))}
                <button
                  className="rounded-md p-1.5 text-ink-muted hover:bg-raised hover:text-critical"
                  aria-label={`Remove ${f.name || "founder"}`}
                  onClick={() => {
                    const next = draft.filter((_, j) => j !== i);
                    setDraft(next);
                    commit(next);
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" /></svg>
                </button>
              </div>
              {(orig?.checks ?? (check ? [{ ...check, label: "Profile" }] : [])).map((c) => (
                <div key={c.label} className="text-[12px] text-ink-muted sm:col-span-4">
                  {c.label}: {c.note}
                </div>
              ))}
            </div>
          );
        })}
      </div>
      <button
        className="w-full border-t border-grid px-5 py-2.5 text-left text-[12.5px] font-semibold text-brand-text hover:bg-row-hover"
        onClick={() => setDraft((d) => [...d, { name: "", role: "Co-Founder", github: null, linkedin: null }])}
      >
        + Add a co-founder
      </button>
    </Card>
  );
}
