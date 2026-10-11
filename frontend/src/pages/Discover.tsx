import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { m } from "motion/react";
import { useSearchParams } from "react-router-dom";
import { api, type StartupSummary } from "../lib/api";
import { compactNum, STAGE_LABEL } from "../lib/format";
import { StartupCard } from "../components/StartupCard";
import { StartupTable } from "../components/StartupTable";
import { Card, Empty, SectionError } from "../components/primitives";
import { RegistryPanel } from "../components/RegistryMatches";
import { useInvestor } from "../lib/investor-context";

const SORTS = [
  { v: "composite_score", l: "Composite score" },
  { v: "growth", l: "Growth potential" },
  { v: "risk", l: "Safety" },
  { v: "founder", l: "Founder credibility" },
  { v: "name", l: "Name (A–Z)" },
  { v: "recent", l: "Recently added" },
];

const DIMENSION_SORTS = new Set(["growth", "risk", "founder"]);
const LIMIT = 24;

function FilterGroup({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center">
        <div className="eyebrow">{title}</div>
        {aside && <div className="ml-auto">{aside}</div>}
      </div>
      {children}
    </div>
  );
}

function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 text-[13.5px] text-ink">
      {label}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors ${
          checked ? "bg-brand" : "bg-line-strong"
        }`}
      >
        <span
          className={`absolute top-[3px] h-4 w-4 rounded-full bg-white shadow transition-[left] ${
            checked ? "left-[19px]" : "left-[3px]"
          }`}
        />
      </button>
    </label>
  );
}

export default function Discover() {
  const { track } = useInvestor();
  const [params, setParams] = useSearchParams();

  const [items, setItems] = useState<StartupSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [sectors, setSectors] = useState<{ sector: string; count: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [firstLoad, setFirstLoad] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"table" | "cards">(() =>
    typeof window !== "undefined" && window.innerWidth < 768 ? "cards" : "table",
  );
  const [sheetOpen, setSheetOpen] = useState(false);
  const [showAllSectors, setShowAllSectors] = useState(false);

  // The global search box writes ?q=; this page reads and writes it back.
  const urlQ = params.get("q") ?? "";
  const [q, setQ] = useState(urlQ);
  const [debouncedQ, setDebouncedQ] = useState(urlQ);
  const [sector, setSector] = useState("");
  const [stage, setStage] = useState("");
  const [sort, setSort] = useState("composite_score");
  const [minScore, setMinScore] = useState(0);
  const [cleanOnly, setCleanOnly] = useState(false);
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [page, setPage] = useState(0);

  useEffect(() => {
    setQ(urlQ);
    setDebouncedQ(urlQ);
    setPage(0);
  }, [urlQ]);

  useEffect(() => {
    api.sectors().then(setSectors).catch(() => {});
  }, []);

  useEffect(() => {
    const t = setTimeout(() => {
      if (q === debouncedQ) return;
      setDebouncedQ(q);
      setPage(0);
      const next = new URLSearchParams(params);
      if (q) next.set("q", q);
      else next.delete("q");
      setParams(next, { replace: true });
    }, 260);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .startups({
        q: debouncedQ || undefined,
        sector: sector || undefined,
        stage: stage || undefined,
        sort,
        min_score: minScore > 0 ? minScore : undefined,
        max_fraud: cleanOnly ? 25 : undefined,
        verified_only: verifiedOnly,
        limit: LIMIT,
        offset: page * LIMIT,
      })
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
      })
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => {
        setLoading(false);
        setFirstLoad(false);
      });
  }, [debouncedQ, sector, stage, sort, minScore, cleanOnly, verifiedOnly, page]);

  useEffect(() => load(), [load]);

  const pages = Math.ceil(total / LIMIT);
  const sortKey = DIMENSION_SORTS.has(sort) ? sort : undefined;

  const clearAll = () => {
    setSector("");
    setStage("");
    setMinScore(0);
    setCleanOnly(false);
    setVerifiedOnly(false);
    setQ("");
    setPage(0);
  };

  const activeChips = useMemo(() => {
    const c: { label: string; clear: () => void }[] = [];
    if (debouncedQ) c.push({ label: `“${debouncedQ}”`, clear: () => setQ("") });
    if (sector) c.push({ label: sector, clear: () => setSector("") });
    if (stage) c.push({ label: STAGE_LABEL[stage] ?? stage, clear: () => setStage("") });
    if (minScore > 0) c.push({ label: `Score ≥ ${minScore}`, clear: () => setMinScore(0) });
    if (cleanOnly) c.push({ label: "Hide flagged", clear: () => setCleanOnly(false) });
    if (verifiedOnly) c.push({ label: "Verified only", clear: () => setVerifiedOnly(false) });
    return c;
  }, [debouncedQ, sector, stage, minScore, cleanOnly, verifiedOnly]);

  const emptyHint = useMemo(() => {
    if (minScore >= 70) return `A minimum score of ${minScore} is very restrictive — try lowering it.`;
    if (verifiedOnly && sector) return `No registry-verified ${sector} startups match. Try removing the verification filter.`;
    if (cleanOnly && minScore > 0) return "Combining a score floor with “hide flagged” is restrictive — relax one.";
    if (sector && stage) return `No ${sector} startups at ${STAGE_LABEL[stage] ?? stage} stage. Try widening the stage.`;
    if (debouncedQ) return `No company matches “${debouncedQ}”. Check spelling or search a sector instead.`;
    return "Try widening the score threshold or clearing the sector filter.";
  }, [minScore, verifiedOnly, sector, cleanOnly, stage, debouncedQ]);

  /* The seed CSVs carry a long tail of free-text sectors with one or two
     companies each. The panel lists the real taxonomy; the tail stays
     reachable through keyword search. */
  const mainSectors = sectors.filter((s) => s.count >= 20);
  const visibleSectors = showAllSectors ? mainSectors : mainSectors.slice(0, 8);

  const filters = (
    <div className="space-y-6">
      <FilterGroup title="Keyword">
        <input
          className="field"
          placeholder="Name or description"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Filter by keyword"
        />
      </FilterGroup>

      <FilterGroup
        title="Industry"
        aside={
          sector ? (
            <button className="text-[12px] font-semibold text-brand-text" onClick={() => setSector("")}>
              Clear
            </button>
          ) : null
        }
      >
        <div className="space-y-0.5" role="radiogroup" aria-label="Industry">
          {visibleSectors.map((s) => {
            const on = sector === s.sector;
            return (
              <button
                key={s.sector}
                role="radio"
                aria-checked={on}
                onClick={() => {
                  setSector(on ? "" : s.sector);
                  setPage(0);
                }}
                className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-[13.5px] transition-colors ${
                  on ? "bg-brand-tint font-semibold text-brand-text" : "text-ink hover:bg-raised"
                }`}
              >
                <span
                  className={`grid h-4 w-4 shrink-0 place-items-center rounded-[5px] border ${
                    on ? "border-brand bg-brand text-white" : "border-line-strong bg-surface"
                  }`}
                >
                  {on && (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden>
                      <path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
                <span className="min-w-0 flex-1 truncate">{s.sector}</span>
                <span className="tnum text-[12px] text-ink-muted">{compactNum(s.count)}</span>
              </button>
            );
          })}
        </div>
        {mainSectors.length > 8 && (
          <button
            className="px-2 text-[12.5px] font-semibold text-brand-text"
            onClick={() => setShowAllSectors((v) => !v)}
          >
            {showAllSectors ? "Show fewer" : `Show ${mainSectors.length - 8} more`}
          </button>
        )}
      </FilterGroup>

      <FilterGroup title="Stage">
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(STAGE_LABEL).map(([v, l]) => {
            const on = stage === v;
            return (
              <button
                key={v}
                aria-pressed={on}
                onClick={() => {
                  setStage(on ? "" : v);
                  setPage(0);
                }}
                className={`rounded-full border px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
                  on
                    ? "border-brand bg-brand-tint text-brand-text"
                    : "border-line-strong bg-surface text-ink-secondary hover:border-ink-disabled"
                }`}
              >
                {l}
              </button>
            );
          })}
        </div>
      </FilterGroup>

      <FilterGroup title="Minimum score" aside={<span className="tnum text-[13px] font-semibold">{minScore}</span>}>
        <input
          type="range"
          min={0}
          max={90}
          step={5}
          value={minScore}
          onChange={(e) => {
            setMinScore(Number(e.target.value));
            setPage(0);
          }}
          className="w-full accent-brand"
          aria-label="Minimum composite score"
        />
      </FilterGroup>

      <FilterGroup title="Trust">
        <div className="space-y-3">
          <Switch
            label="Registry-verified only"
            checked={verifiedOnly}
            onChange={(v) => {
              setVerifiedOnly(v);
              setPage(0);
            }}
          />
          <Switch
            label="Hide flagged companies"
            checked={cleanOnly}
            onChange={(v) => {
              setCleanOnly(v);
              setPage(0);
            }}
          />
        </div>
      </FilterGroup>
    </div>
  );

  return (
    <div className="animate-in grid gap-6 lg:grid-cols-[272px_minmax(0,1fr)]">
      {/* ───── filter panel (desktop) ───── */}
      <aside className="hidden lg:block">
        <div className="card card-lit sticky top-[88px] max-h-[calc(100vh-112px)] overflow-y-auto p-5">
          <div className="mb-5 flex items-center">
            <h2 className="text-[16px] font-bold">Filters</h2>
            {activeChips.length > 0 && (
              <button className="ml-auto text-[13px] font-semibold text-brand-text" onClick={clearAll}>
                Clear all
              </button>
            )}
          </div>
          {filters}
        </div>
      </aside>

      {/* ───── results ───── */}
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0">
            <div className="eyebrow mb-1">Discover</div>
            <h1 className="text-[26px] font-extrabold tracking-tight">Organizations</h1>
            <p className="mt-0.5 text-[14px] text-ink-muted">
              {loading && firstLoad ? (
                "Searching…"
              ) : (
                <>
                  <b className="tnum font-semibold text-ink">{total.toLocaleString("en-US")}</b>{" "}
                  {total === 1 ? "result matches" : "results match"} your filters
                </>
              )}
            </p>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button className="btn lg:hidden" onClick={() => setSheetOpen(true)}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M4 6h16M7 12h10M10 18h4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
              </svg>
              Filters{activeChips.length ? ` (${activeChips.length})` : ""}
            </button>
            <label className="flex items-center gap-2 text-[13px] text-ink-muted">
              <span className="hidden sm:inline">Sort by</span>
              <select
                className="field h-10 w-auto cursor-pointer py-0"
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value);
                  setPage(0);
                }}
                aria-label="Sort results"
              >
                {SORTS.map((s) => (
                  <option key={s.v} value={s.v}>
                    {s.l}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex h-10 overflow-hidden rounded-[10px] border border-line-strong bg-surface" role="group" aria-label="View">
              {(["table", "cards"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  aria-pressed={view === v}
                  className={`relative isolate px-3.5 text-[13px] font-semibold capitalize transition-colors ${
                    view === v ? "text-brand-text" : "text-ink-secondary hover:bg-raised"
                  }`}
                >
                  {view === v && (
                    <m.span
                      layoutId="discover-view"
                      className="absolute inset-0 -z-10 bg-brand-tint"
                      transition={{ type: "spring", stiffness: 500, damping: 38 }}
                    />
                  )}
                  {v}
                </button>
              ))}
            </div>
          </div>
        </div>

        {activeChips.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {activeChips.map((c) => (
              <button
                key={c.label}
                onClick={c.clear}
                className="chip chip-brand cursor-pointer transition-colors hover:border-brand-dim"
              >
                {c.label}
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                </svg>
                <span className="sr-only">Remove filter</span>
              </button>
            ))}
            <button onClick={clearAll} className="ml-1 text-[12.5px] font-semibold text-ink-muted hover:text-ink">
              Clear all
            </button>
          </div>
        )}

        {debouncedQ.trim().length >= 2 && !loading && items.length === 0 && <RegistryPanel q={debouncedQ} />}

        {error ? (
          <Card>
            <SectionError message={error} onRetry={load} />
          </Card>
        ) : firstLoad && loading ? (
          <div className="skeleton h-[560px]" />
        ) : items.length === 0 ? (
          <Card>
            <Empty
              title="No startups match those filters"
              hint={emptyHint}
              action={
                activeChips.length > 0 ? (
                  <button className="btn" onClick={clearAll}>
                    Clear all filters
                  </button>
                ) : undefined
              }
            />
          </Card>
        ) : (
          <>
            {/* Stale results stay visible while refetching. */}
            <div style={{ opacity: loading ? 0.55 : 1, transition: "opacity 150ms ease" }}>
              {view === "table" ? (
                <StartupTable
                  items={items}
                  sortKey={sort}
                  onSort={(k) => {
                    setSort(k);
                    setPage(0);
                  }}
                  onOpen={(id) => track("view", id)}
                />
              ) : (
                <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 2xl:grid-cols-3">
                  {items.map((s) => (
                    <StartupCard key={s.startup_id} s={s} sortKey={sortKey} onOpen={() => track("view", s.startup_id)} />
                  ))}
                </div>
              )}
            </div>

            {pages > 1 && (
              <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-ink-muted">
                <span>
                  Showing <b className="tnum text-ink">{page * LIMIT + 1}–{Math.min(total, (page + 1) * LIMIT)}</b> of{" "}
                  <b className="tnum text-ink">{total.toLocaleString("en-US")}</b>
                </span>
                <div className="flex items-center gap-2">
                  <button
                    className="btn h-9"
                    disabled={page === 0}
                    onClick={() => {
                      setPage((p) => p - 1);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  >
                    Previous
                  </button>
                  <span className="tnum px-2">
                    {page + 1} / {compactNum(pages)}
                  </span>
                  <button
                    className="btn h-9"
                    disabled={page >= pages - 1}
                    onClick={() => {
                      setPage((p) => p + 1);
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
            {debouncedQ.trim().length >= 2 && <RegistryPanel q={debouncedQ} />}
          </>
        )}
      </div>

      {/* ───── mobile filter sheet ───── */}
      {sheetOpen && (
        <div className="fixed inset-0 z-[60] lg:hidden">
          <div className="absolute inset-0 bg-scrim" onClick={() => setSheetOpen(false)} />
          <div className="overlay-panel absolute inset-x-0 bottom-0 max-h-[86vh] overflow-y-auto rounded-b-none p-5">
            <div className="mb-5 flex items-center gap-2">
              <h2 className="text-[17px] font-bold">Filters</h2>
              <div className="ml-auto flex items-center gap-2">
                {activeChips.length > 0 && (
                  <button className="btn h-9 text-[13px]" onClick={clearAll}>
                    Clear
                  </button>
                )}
                <button className="btn btn-primary h-9 text-[13px]" onClick={() => setSheetOpen(false)}>
                  Show {total.toLocaleString("en-US")}
                </button>
              </div>
            </div>
            {filters}
          </div>
        </div>
      )}
    </div>
  );
}
