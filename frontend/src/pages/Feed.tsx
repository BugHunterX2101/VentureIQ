import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, m as motion } from "motion/react";
import { useToast } from "../components/ui/Toast";
import { Link } from "react-router-dom";
import { api, type Match } from "../lib/api";
import { stageLabel } from "../lib/format";
import { StartupCard } from "../components/StartupCard";
import { Badge, Card, Empty, SectionError } from "../components/primitives";
import { useInvestor } from "../lib/investor-context";

/** One contributing signal in the match breakdown. A match is never a bare
 *  number — if the system can't say why two parties fit, it has no business
 *  ranking them (MASTER §7.5). */
function SignalBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-[72px] shrink-0 text-[12px] text-ink-muted">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-track">
        <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(2, value)}%` }} />
      </div>
      <span className="tnum w-7 shrink-0 text-right text-[12px] font-semibold text-ink-secondary">
        {Math.round(value)}
      </span>
    </div>
  );
}

export default function Feed() {
  const { current, track } = useInvestor();
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [excludeSeen, setExcludeSeen] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const toast = useToast();

  const load = useCallback(() => {
    if (!current) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .feed(current.investor_id, { limit: 24, exclude_seen: excludeSeen })
      .then(setMatches)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
  }, [current, excludeSeen]);

  useEffect(() => load(), [load]);

  if (!current) {
    return (
      <Card>
        <Empty
          title="No investor profile selected"
          hint="Your stated mandate is the entire ranking signal until behavioural learning kicks in."
          action={
            <Link to="/onboarding" className="btn btn-primary">
              Set up profile
            </Link>
          }
        />
      </Card>
    );
  }

  const coldStart = matches[0]?.cold_start;
  const pref = current.preference;
  const visible = matches.filter((m) => !dismissed.has(m.startup.startup_id));

  return (
    <div className="animate-in space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">
            Deal feed for {current.name}
          </h1>
          <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-ink-muted">
            Ranked by stated mandate, your behaviour on the platform, co-investor network
            position, and each company's own quality score.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-ink-secondary">
          <input
            type="checkbox"
            checked={excludeSeen}
            onChange={(e) => setExcludeSeen(e.target.checked)}
            className="accent-brand"
          />
          Hide companies I've seen
        </label>
      </div>

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2.5">
          <div className="min-w-0">
            <span className="eyebrow">Mandate</span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {pref?.preferred_sectors.map((s) => (
                <span key={s} className="chip">
                  {s}
                </span>
              ))}
              {pref?.stage_preference.map((s) => (
                <span key={s} className="chip">
                  {stageLabel(s)}
                </span>
              ))}
              {pref?.risk_tolerance && (
                <span className="chip capitalize">{pref.risk_tolerance} risk</span>
              )}
            </div>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Badge tone={current.kyc_status === "verified" ? "good" : "warning"}>
              KYC {current.kyc_status}
            </Badge>
            {coldStart && <Badge tone="warning">Cold start — stated preferences only</Badge>}
          </div>
        </div>
      </Card>

      {error ? (
        <Card>
          <SectionError message={error} onRetry={load} />
        </Card>
      ) : loading ? (
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 330 }} />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <Card>
          <Empty
            title="No matches yet"
            hint="Broaden your mandate — add sectors or stages — to see ranked opportunities."
            action={
              <Link to="/onboarding" className="btn">
                Edit mandate
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 2xl:grid-cols-3">
          <AnimatePresence initial={false} mode="popLayout">
          {visible.map((m) => (
            <motion.div
              key={m.startup.startup_id}
              layout
              exit={{ opacity: 0, scale: 0.94, transition: { duration: 0.22 } }}
              transition={{ type: "spring", stiffness: 420, damping: 38 }}
              className="flex flex-col gap-2"
            >
              <StartupCard
                s={m.startup}
                matchScore={m.match_score}
                reasons={m.reasons}
                onOpen={() => track("view", m.startup.startup_id)}
              />
              <Card className="p-4" lit={false}>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="eyebrow">Match breakdown</span>
                  <button
                    className="text-[12.5px] font-semibold text-ink-muted transition-colors hover:text-critical"
                    onClick={() => {
                      track("dismiss", m.startup.startup_id);
                      setDismissed((d) => new Set(d).add(m.startup.startup_id));
                      toast({ title: `${m.startup.legal_name} dismissed`, body: "Your feed will learn from this." });
                    }}
                  >
                    Dismiss
                  </button>
                </div>
                <div className="space-y-1.5">
                  <SignalBar label="Mandate" value={m.preference_score} />
                  <SignalBar label="Behaviour" value={m.behavioral_score} />
                  <SignalBar label="Network" value={m.network_score} />
                  <SignalBar label="Quality" value={m.quality_score} />
                </div>
              </Card>
            </motion.div>
          ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
