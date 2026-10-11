import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, m } from "motion/react";
import { api, type WatchlistItem } from "../lib/api";
import { scoreBand, stageLabel } from "../lib/format";
import { Badge, Card, Empty, SectionError, SkeletonRows } from "../components/primitives";
import { LogoTile } from "../components/primitives";
import { useToast } from "../components/ui/Toast";

const STAGES = [
  { key: "watching", label: "Watching", tone: "brand" as const },
  { key: "contacted", label: "Contacted", tone: "good" as const },
  { key: "passed", label: "Passed", tone: "neutral" as const },
];

/** The investor's own pipeline: saved companies, a private note, and where
 *  each one stands. Saving also feeds the matcher as a behavioural signal. */
export default function Saved() {
  const toast = useToast();
  const [items, setItems] = useState<WatchlistItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await api.watchlist());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function move(item: WatchlistItem, stage: string) {
    setItems((prev) => prev?.map((i) => (i.item_id === item.item_id ? { ...i, stage: stage as never } : i)) ?? null);
    try {
      await api.watch(item.startup_id, { stage, note: item.note });
    } catch (e) {
      setError((e as Error).message);
      void load();
    }
  }

  async function saveNote(item: WatchlistItem) {
    setEditing(null);
    setItems((prev) => prev?.map((i) => (i.item_id === item.item_id ? { ...i, note: draft || null } : i)) ?? null);
    try {
      await api.watch(item.startup_id, { note: draft, stage: item.stage });
      toast({ title: "Note saved", tone: "good" });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(item: WatchlistItem) {
    setItems((prev) => prev?.filter((i) => i.item_id !== item.item_id) ?? null);
    try {
      await api.unwatch(item.startup_id);
      toast({ title: `${item.startup?.legal_name ?? "Company"} removed from your list` });
    } catch (e) {
      setError((e as Error).message);
      void load();
    }
  }

  const shown = (items ?? []).filter((i) => filter === "all" || i.stage === filter);

  return (
    <div className="animate-in space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow mb-1">Your pipeline</div>
          <h1 className="text-[28px] font-extrabold leading-tight tracking-tight">Saved companies</h1>
          <p className="mt-1 text-[14px] text-ink-secondary">
            Private to you. Saving also tells the matcher what you like.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[{ key: "all", label: "All" }, ...STAGES].map((s) => {
            const n = s.key === "all" ? items?.length ?? 0 : (items ?? []).filter((i) => i.stage === s.key).length;
            return (
              <button
                key={s.key}
                aria-pressed={filter === s.key}
                onClick={() => setFilter(s.key)}
                className={`relative isolate rounded-full border px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
                  filter === s.key ? "border-brand text-brand-text" : "border-line-strong text-ink-secondary hover:border-ink-disabled"
                }`}
              >
                {filter === s.key && (
                  <m.span layoutId="saved-filter" className="absolute inset-0 -z-10 rounded-full bg-brand-tint" />
                )}
                {s.label} <span className="tnum text-ink-muted">{n}</span>
              </button>
            );
          })}
        </div>
      </div>

      {error && (
        <Card className="p-5">
          <SectionError message={error} onRetry={() => void load()} />
        </Card>
      )}

      {items === null ? (
        <Card className="p-5">
          <SkeletonRows n={4} />
        </Card>
      ) : shown.length === 0 ? (
        <Card>
          <Empty
            title={items.length === 0 ? "Nothing saved yet" : `Nothing marked "${filter}"`}
            hint={items.length === 0 ? "Open a company and press Save to start your pipeline." : undefined}
            action={
              <Link to="/discover" className="btn btn-primary">
                Browse companies
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="space-y-3">
          <AnimatePresence initial={false}>
            {shown.map((item) => {
              const s = item.startup;
              return (
                <m.div
                  key={item.item_id}
                  layout
                  exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.2 } }}
                  className="card card-lit p-4 sm:p-5"
                >
                  <div className="flex flex-wrap items-start gap-4">
                    <LogoTile name={s?.legal_name ?? "?"} src={s?.logo_url} size={40} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link to={`/startup/${item.startup_id}`} className="truncate text-[16px] font-bold hover:text-brand-text">
                          {s?.legal_name ?? "Unknown company"}
                        </Link>
                        {s?.verified && <Badge tone="good">Registry-verified</Badge>}
                      </div>
                      <div className="mt-0.5 text-[12.5px] text-ink-muted">
                        {[s?.sector, s?.stage ? stageLabel(s.stage) : null, s?.hq_city].filter(Boolean).join(" · ")}
                      </div>
                      {editing === item.item_id ? (
                        <div className="mt-2 flex gap-2">
                          <input
                            autoFocus
                            className="field h-9 min-w-0 flex-1"
                            value={draft}
                            placeholder="Why are you watching this?"
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") void saveNote(item);
                              if (e.key === "Escape") setEditing(null);
                            }}
                          />
                          <button className="btn h-9" onClick={() => void saveNote(item)}>Save</button>
                        </div>
                      ) : (
                        <button
                          className="mt-1.5 block max-w-full truncate text-left text-[13px] text-ink-secondary hover:text-ink"
                          onClick={() => {
                            setEditing(item.item_id);
                            setDraft(item.note ?? "");
                          }}
                        >
                          {item.note || <span className="text-ink-muted">Add a note…</span>}
                        </button>
                      )}
                    </div>

                    <div className="flex items-center gap-4">
                      {s?.composite_score !== null && s?.composite_score !== undefined && (
                        <div className="text-right">
                          <div className="tnum text-[20px] font-semibold" style={{ color: scoreBand(s.composite_score).color }}>
                            {s.composite_score.toFixed(1)}
                          </div>
                          <div className="text-[11px] text-ink-muted">composite</div>
                        </div>
                      )}
                      <select
                        aria-label={`Pipeline stage for ${s?.legal_name ?? "company"}`}
                        className="field h-9"
                        value={item.stage}
                        onChange={(e) => void move(item, e.target.value)}
                      >
                        {STAGES.map((st) => (
                          <option key={st.key} value={st.key}>{st.label}</option>
                        ))}
                      </select>
                      <button
                        className="rounded-md p-1.5 text-ink-muted hover:bg-raised hover:text-critical"
                        aria-label={`Remove ${s?.legal_name ?? "company"} from saved`}
                        onClick={() => void remove(item)}
                      >
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                          <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </m.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
