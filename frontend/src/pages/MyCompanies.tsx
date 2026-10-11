import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { m } from "motion/react";
import { api, type MyStartup } from "../lib/api";
import { relativeTime, scoreBand, stageLabel } from "../lib/format";
import { Badge, Card, Empty, LogoTile, SectionError, SkeletonRows } from "../components/primitives";
import { useToast } from "../components/ui/Toast";
import { MentorInbox } from "../components/Mentorship";

/** What a founder sees about the companies they registered: the four scores as
 *  investors see them, open flags, and what is still unverified. */
export default function MyCompanies() {
  const toast = useToast();
  const [items, setItems] = useState<MyStartup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [listing, setListing] = useState<string | null>(null);
  const [form, setForm] = useState({ ask: "500000", equity: "5", rofr: "7" });
  const [busy, setBusy] = useState(false);

  async function list(startupId: string) {
    setBusy(true);
    try {
      await api.createListing(startupId, Number(form.ask), Number(form.equity), Number(form.rofr));
      toast({
        title: "Listed on the marketplace",
        body: "Simulated: offers are checked against the platform's rules, but no money moves.",
        tone: "good",
      });
      setListing(null);
    } catch (e) {
      toast({ title: "Couldn't list it", body: (e as Error).message.slice(0, 200), tone: "warning" });
    } finally {
      setBusy(false);
    }
  }

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await api.myStartups());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="animate-in space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-1">Founder</div>
          <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">Your companies</h1>
          <p className="mt-1 text-[14px] text-ink-secondary">
            Exactly what an investor sees — including anything flagged for review.
          </p>
        </div>
        <Link to="/register" className="btn btn-primary">Register a company</Link>
      </div>

      {error && (
        <Card className="p-5">
          <SectionError message={error} onRetry={() => void load()} />
        </Card>
      )}

      {items === null ? (
        <Card className="p-5"><SkeletonRows n={2} height={120} /></Card>
      ) : items.length === 0 ? (
        <Card>
          <Empty
            title="You haven't registered a company yet"
            hint="The agent researches it from your website and shows you what it could verify."
            action={<Link to="/register" className="btn btn-primary">Register a company</Link>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {items.map((s, i) => {
            const scores: { label: string; value: number | null; invert?: boolean }[] = [
              { label: "Growth", value: s.growth_potential_score },
              { label: "Safety", value: s.risk_level_score },
              { label: "Founder", value: s.founder_credibility_score },
              { label: "Fraud ↓", value: s.fraud_likelihood_score, invert: true },
            ];
            return (
              <m.div
                key={s.startup_id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="card card-lit p-5"
              >
                <div className="flex flex-wrap items-start gap-3">
                  <LogoTile name={s.legal_name} size={40} />
                  <div className="min-w-0 flex-1">
                    <Link to={`/startup/${s.startup_id}`} className="truncate text-[17px] font-bold hover:text-brand-text">
                      {s.legal_name}
                    </Link>
                    <div className="mt-0.5 text-[12.5px] text-ink-muted">
                      {[s.sector, stageLabel(s.stage), s.hq_city].filter(Boolean).join(" · ")}
                      {s.created_at ? ` · registered ${relativeTime(s.created_at)}` : ""}
                    </div>
                  </div>
                  {s.verified ? (
                    <Badge tone="good">Registry-verified</Badge>
                  ) : (
                    <Badge tone="warning">Unverified</Badge>
                  )}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {scores.map((x) => (
                    <div key={x.label} className="rounded-xl border border-line bg-raised px-3 py-2">
                      <div className="text-[11.5px] text-ink-muted">{x.label}</div>
                      <div
                        className="tnum text-[20px] font-semibold"
                        style={{ color: x.value === null ? "var(--color-ink-muted)" : scoreBand(x.invert ? 100 - x.value : x.value).color }}
                      >
                        {x.value === null ? "—" : Math.round(x.value)}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2 text-[12.5px]">
                  {s.composite_score !== null && (
                    <span className="text-ink-secondary">
                      Composite <b className="tnum" style={{ color: scoreBand(s.composite_score).color }}>{s.composite_score.toFixed(1)}</b>
                      {s.confidence ? ` · ${s.confidence} confidence` : ""}
                    </span>
                  )}
                  {s.cin && <span className="chip tnum">{s.cin}</span>}
                </div>

                {s.open_flags > 0 && (
                  <div className="mt-3 rounded-xl border border-warning-line bg-warning-tint px-3 py-2.5 text-[12.5px] leading-snug text-warning-text">
                    <b>{s.open_flags} open flag{s.open_flags > 1 ? "s" : ""}</b>
                    {s.top_flag ? ` — ${s.top_flag}` : ""}
                    <div className="mt-0.5 text-ink-muted">
                      Algorithms flag; a human reviews. Fix the underlying data and re-run the agent.
                    </div>
                  </div>
                )}

                <div className="mt-4 flex flex-wrap gap-2">
                  <Link to={`/startup/${s.startup_id}`} className="btn h-9">Open profile</Link>
                  <Link to={`/startup/${s.startup_id}#provenance`} className="btn h-9">See what was verified</Link>
                  <button className="btn h-9" onClick={() => setListing(listing === s.startup_id ? null : s.startup_id)}>
                    {listing === s.startup_id ? "Cancel" : "List on marketplace"}
                  </button>
                </div>

                {listing === s.startup_id && (
                  <div className="mt-3 rounded-xl border border-line bg-raised p-3">
                    <div className="grid gap-2.5 sm:grid-cols-3">
                      <label className="text-[12.5px] font-semibold">
                        Ask (USD)
                        <input className="field tnum mt-1 h-10 w-full" type="number" min={1} value={form.ask}
                               onChange={(e) => setForm((f) => ({ ...f, ask: e.target.value }))} />
                      </label>
                      <label className="text-[12.5px] font-semibold">
                        Equity offered %
                        <input className="field tnum mt-1 h-10 w-full" type="number" step="0.1" min={0.1} max={100} value={form.equity}
                               onChange={(e) => setForm((f) => ({ ...f, equity: e.target.value }))} />
                      </label>
                      <label className="text-[12.5px] font-semibold">
                        RoFR window (days)
                        <input className="field tnum mt-1 h-10 w-full" type="number" min={0} max={90} value={form.rofr}
                               onChange={(e) => setForm((f) => ({ ...f, rofr: e.target.value }))} />
                      </label>
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <button className="btn btn-primary h-9" disabled={busy} onClick={() => void list(s.startup_id)}>
                        {busy ? "Listing…" : "Create listing"}
                      </button>
                      <span className="text-[12px] text-ink-muted">
                        Simulated. Existing holders get the RoFR window before any settlement.
                      </span>
                    </div>
                  </div>
                )}

                <MentorInbox startupId={s.startup_id} startupName={s.legal_name} />
              </m.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
