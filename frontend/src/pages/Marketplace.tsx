import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, m } from "motion/react";
import { api, type ComplianceVerdict, type MarketOffer, type MarketRule } from "../lib/api";
import { compactUsd } from "../lib/format";
import { Badge, Card, Empty, SectionError, SkeletonRows } from "../components/primitives";
import { useAuth } from "../lib/auth";
import { useToast } from "../components/ui/Toast";

const STATUS_TONE: Record<string, "brand" | "good" | "serious" | "neutral"> = {
  offered: "brand",
  rofr_window: "good",
  settled_simulated: "good",
  declined: "neutral",
};

function StatusBadge({ status }: { status: string }) {
  const label = {
    offered: "Offered",
    rofr_window: "Accepted · RoFR window",
    settled_simulated: "Settled (simulated)",
    declined: "Declined",
  }[status] ?? status;
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{label}</Badge>;
}

/** The secondary marketplace — a complete flow that never moves money. */
export default function Marketplace() {
  const { user } = useAuth();
  const toast = useToast();
  const [rules, setRules] = useState<{ disclaimer: string; rules: MarketRule[]; accredited_threshold_usd: number } | null>(null);
  const [listings, setListings] = useState<any[] | null>(null);
  const [offers, setOffers] = useState<MarketOffer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<ComplianceVerdict[] | null>(null);
  const [openFor, setOpenFor] = useState<string | null>(null);
  const [form, setForm] = useState({ amount: "100000", equity_pct: "1", message: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [r, l] = await Promise.all([api.marketRules(), api.listings()]);
      setRules(r);
      setListings(l.items);
      if (user) setOffers(await api.myOffers());
    } catch (e) {
      setError((e as Error).message);
    }
  }, [user]);

  useEffect(() => {
    void load();
  }, [load]);

  async function offer(listingId: string) {
    setBusy(true);
    setBlocked(null);
    try {
      await api.makeOffer(listingId, {
        amount: Number(form.amount),
        equity_pct: form.equity_pct ? Number(form.equity_pct) : null,
        message: form.message || null,
      });
      toast({ title: "Offer recorded", body: "Simulated — no money moved.", tone: "good" });
      setOpenFor(null);
      await load();
    } catch (e) {
      // The API returns every failed rule, so show them rather than a generic error.
      const failed = (e as { detail?: { failed?: ComplianceVerdict[] } }).detail?.failed;
      if (failed?.length) setBlocked(failed);
      else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function act(offerId: string, action: "accept" | "decline" | "settle") {
    try {
      const r = await api.offerAction(offerId, action);
      toast({
        title: { accept: "Offer accepted", decline: "Offer declined", settle: "Settled (simulated)" }[action],
        body: r.next ?? r.settlement?.note,
        tone: "good",
      });
      await load();
    } catch (e) {
      toast({ title: "Couldn't do that", body: (e as Error).message.slice(0, 160), tone: "warning" });
    }
  }

  return (
    <div className="animate-in space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-1">Secondary marketplace</div>
          <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">Listings</h1>
          <p className="mt-1 max-w-[640px] text-[14px] leading-relaxed text-ink-secondary">
            {rules?.disclaimer ??
              "No money moves and no equity is transferred; escrow is a state machine standing in for a licensed provider."}
          </p>
        </div>
        <Badge tone="warning">Simulated end to end</Badge>
      </div>

      {error && <Card className="p-5"><SectionError message={error} onRetry={() => void load()} /></Card>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          {listings === null ? (
            <Card className="p-5"><SkeletonRows n={3} height={90} /></Card>
          ) : listings.length === 0 ? (
            <Card>
              <Empty
                title="No listings yet"
                hint={user?.role === "founder"
                  ? "List one of your companies from its profile to see the flow."
                  : "Founders list companies here; offers are checked against the rules on the right."}
              />
            </Card>
          ) : (
            listings.map((l) => (
              <Card key={l.listing_id} className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link to={`/startup/${l.startup_id}`} className="text-[17px] font-bold hover:text-brand-text">
                      {l.startup_name ?? l.legal_name}
                    </Link>
                    <div className="mt-0.5 text-[12.5px] text-ink-muted">
                      {[l.sector, l.stage].filter(Boolean).join(" · ")}
                      {l.composite_score !== null && l.composite_score !== undefined
                        ? ` · composite ${l.composite_score.toFixed(1)}`
                        : ""}
                    </div>
                  </div>
                  <Badge tone={l.status === "open" ? "good" : "neutral"}>{l.status?.replace(/_/g, " ")}</Badge>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    ["Ask", compactUsd(l.ask_amount)],
                    ["Equity", l.equity_offered_pct ? `${l.equity_offered_pct}%` : "—"],
                    ["Implied valuation", l.implied_valuation ? compactUsd(l.implied_valuation) : "—"],
                    ["Fair value estimate", l.fair_value_estimate ? compactUsd(l.fair_value_estimate) : "—"],
                  ].map(([label, value]) => (
                    <div key={label as string}>
                      <div className="text-[11.5px] text-ink-muted">{label}</div>
                      <div className="tnum text-[16px] font-semibold">{value as string}</div>
                    </div>
                  ))}
                </div>

                {user?.role === "investor" && l.status === "open" && (
                  <div className="mt-4">
                    {openFor === l.listing_id ? (
                      <div className="rounded-xl border border-line bg-raised p-3">
                        <div className="grid gap-2.5 sm:grid-cols-3">
                          <label className="text-[12.5px] font-semibold">
                            Amount (USD)
                            <input className="field tnum mt-1 h-10 w-full" type="number" min={1} value={form.amount}
                                   onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))} />
                          </label>
                          <label className="text-[12.5px] font-semibold">
                            Equity %
                            <input className="field tnum mt-1 h-10 w-full" type="number" step="0.1" min={0} value={form.equity_pct}
                                   onChange={(e) => setForm((f) => ({ ...f, equity_pct: e.target.value }))} />
                          </label>
                          <label className="text-[12.5px] font-semibold sm:col-span-1">
                            Message
                            <input className="field mt-1 h-10 w-full" value={form.message}
                                   onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))} />
                          </label>
                        </div>
                        <div className="mt-3 flex gap-2">
                          <button className="btn btn-primary h-9" disabled={busy} onClick={() => void offer(l.listing_id)}>
                            {busy ? "Checking rules…" : "Submit offer"}
                          </button>
                          <button className="btn h-9" onClick={() => { setOpenFor(null); setBlocked(null); }}>Cancel</button>
                        </div>
                        <AnimatePresence>
                          {blocked && (
                            <m.ul initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0 }}
                                  className="mt-3 space-y-1.5 overflow-hidden border-t border-line pt-3">
                              {blocked.map((v) => (
                                <li key={v.id} className="text-[12.5px]">
                                  <span className="font-semibold text-serious">✕ {v.rule}</span>
                                  <span className="block text-ink-muted">{v.detail} — {v.why}</span>
                                </li>
                              ))}
                            </m.ul>
                          )}
                        </AnimatePresence>
                      </div>
                    ) : (
                      <button className="btn btn-primary h-9" onClick={() => { setOpenFor(l.listing_id); setBlocked(null); }}>
                        Make an offer
                      </button>
                    )}
                  </div>
                )}
              </Card>
            ))
          )}

          {offers.length > 0 && (
            <Card className="p-5">
              <h2 className="text-[17px] font-bold">{user?.role === "founder" ? "Offers on your companies" : "Your offers"}</h2>
              <div className="mt-3 divide-y divide-grid">
                {offers.map((o) => (
                  <div key={o.offer_id} className="flex flex-wrap items-center gap-3 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] font-semibold">
                        {o.startup?.legal_name ?? "Company"} · <span className="tnum">{compactUsd(o.amount)}</span>
                        {o.equity_pct ? ` for ${o.equity_pct}%` : ""}
                      </div>
                      {o.message && <div className="truncate text-[12.5px] text-ink-muted">“{o.message}”</div>}
                      {o.rofr_expires_at && o.status === "rofr_window" && (
                        <div className="text-[12px] text-ink-muted">
                          Right-of-first-refusal window ends {new Date(o.rofr_expires_at).toLocaleDateString()}
                        </div>
                      )}
                    </div>
                    <StatusBadge status={o.status} />
                    {user?.role === "founder" && (
                      <div className="flex gap-2">
                        {o.status === "offered" && (
                          <>
                            <button className="btn h-8 px-3 text-[12.5px]" onClick={() => void act(o.offer_id, "accept")}>Accept</button>
                            <button className="btn h-8 px-3 text-[12.5px]" onClick={() => void act(o.offer_id, "decline")}>Decline</button>
                          </>
                        )}
                        {o.status === "rofr_window" && (
                          <button className="btn h-8 px-3 text-[12.5px]" onClick={() => void act(o.offer_id, "settle")}>
                            Settle (simulated)
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        {/* ── the rules, in the open ───────────────────────────────────── */}
        <Card className="h-fit p-5">
          <h2 className="text-[16px] font-bold">What is enforced</h2>
          <p className="mt-0.5 text-[12.5px] text-ink-muted">
            Every offer is evaluated against these, and failures are returned with reasons.
          </p>
          <ul className="mt-3 space-y-3">
            {(rules?.rules ?? []).map((r) => (
              <li key={r.id} className="text-[12.5px]">
                <span className="font-semibold">{r.rule}</span>
                <span className="block text-ink-muted">{r.why}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 border-t border-line pt-3 text-[11.5px] leading-relaxed text-ink-muted">
            Selling private-company shares is SEBI/RBI-regulated. Nothing here touches a payment rail;
            settlement records a state change and an audit entry, nothing more.
          </p>
        </Card>
      </div>
    </div>
  );
}
