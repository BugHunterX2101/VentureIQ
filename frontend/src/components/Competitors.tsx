import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { m } from "motion/react";
import { api, type CompetitorRow, type CompetitorSet } from "../lib/api";
import { compactNum, compactUsd, scoreBand, stageLabel } from "../lib/format";
import { Badge, Card, Empty, LogoTile, SectionError } from "./primitives";

/** The company against the companies it is actually competing with.
 *
 *  A list of peers is only half an answer — the useful question is where this
 *  company sits among them. So the subject sits in the same table as its
 *  competitors, with the set's median as its own row, and every number is
 *  drawn as a share of the largest value in that column. Reading down a
 *  column then answers "who is ahead" without doing arithmetic.
 */

type Metric = {
  key: keyof CompetitorRow | "composite_score";
  label: string;
  format: (v: number | null) => string;
  /** Higher is better for most, but not for fraud. */
  invert?: boolean;
};

const METRICS: Metric[] = [
  { key: "total_funding_usd", label: "Raised", format: (v) => (v ? compactUsd(v) : "—") },
  { key: "revenue", label: "Revenue", format: (v) => (v ? compactUsd(v) : "—") },
  { key: "employee_count", label: "Team", format: (v) => (v ? compactNum(v) : "—") },
  { key: "composite_score", label: "Composite", format: (v) => (v == null ? "—" : v.toFixed(1)) },
  { key: "growth_potential_score", label: "Growth", format: (v) => (v == null ? "—" : v.toFixed(0)) },
  { key: "fraud_likelihood_score", label: "Fraud", format: (v) => (v == null ? "—" : v.toFixed(0)), invert: true },
];

function Bar({ value, max, tone, invert }: { value: number | null; max: number; tone?: string; invert?: boolean }) {
  const pct = value == null || max <= 0 ? 0 : Math.min(100, (value / max) * 100);
  return (
    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-track">
      <m.div
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        className="h-full rounded-full"
        style={{ backgroundColor: tone ?? (invert ? "var(--color-warning)" : "var(--color-brand)") }}
      />
    </div>
  );
}

function Cell({ row, metric, max }: { row: CompetitorRow; metric: Metric; max: number }) {
  const value = (row as unknown as Record<string, number | null>)[metric.key] ?? null;
  const tone =
    metric.key === "composite_score" && value != null ? scoreBand(value).color : undefined;
  return (
    <td className="px-3 py-3 text-right align-middle">
      <span className="tnum text-[13px] font-semibold" style={{ color: tone }}>
        {metric.format(value ?? null)}
      </span>
      <Bar value={value ?? null} max={max} tone={tone} invert={metric.invert} />
    </td>
  );
}

export default function Competitors({ startupId }: { startupId: string }) {
  const [data, setData] = useState<CompetitorSet | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    api
      .competitors(startupId, 8)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(String((e as Error).message)));
    return () => {
      live = false;
    };
  }, [startupId]);

  if (error)
    return (
      <Card className="p-5">
        <SectionError message={error} />
      </Card>
    );
  if (!data) return <div className="skeleton h-64 rounded-2xl" />;
  if (!data.peers.length)
    return (
      <Card className="p-5">
        <Empty
          title="No close comparables"
          hint="Nothing in the corpus is near enough on description, stage and sector to compare fairly."
        />
      </Card>
    );

  // Column scales come from every row on screen, the subject included, so the
  // bars are comparable across the table rather than per-row.
  const all = [data.subject, ...data.peers];
  const maxes = Object.fromEntries(
    METRICS.map((mt) => [
      mt.key,
      Math.max(
        0,
        ...all.map((r) => Number((r as unknown as Record<string, number | null>)[mt.key] ?? 0)),
        Number(data.median[mt.key as string] ?? 0),
      ),
    ]),
  ) as Record<string, number>;

  const medianRow = {
    startup_id: "__median__",
    legal_name: "Median of this set",
    ...data.median,
  } as unknown as CompetitorRow;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="min-w-0 flex-1">
          <h2 className="text-[17px] font-bold tracking-tight">Competitors</h2>
          <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-ink-muted">{data.basis}</p>
        </div>
        <Badge tone="brand">{data.peers.length} compared</Badge>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse">
          <thead>
            <tr className="border-b border-line bg-plane">
              <th className="sticky left-0 z-10 bg-plane px-5 py-2.5 text-left text-[11.5px] font-bold uppercase tracking-wide text-ink-muted">
                Company
              </th>
              <th className="px-3 py-2.5 text-left text-[11.5px] font-bold uppercase tracking-wide text-ink-muted">
                Stage
              </th>
              {METRICS.map((mt) => (
                <th
                  key={String(mt.key)}
                  className="px-3 py-2.5 text-right text-[11.5px] font-bold uppercase tracking-wide text-ink-muted"
                >
                  {mt.label}
                </th>
              ))}
              <th className="px-3 py-2.5 text-right text-[11.5px] font-bold uppercase tracking-wide text-ink-muted">
                Match
              </th>
            </tr>
          </thead>
          <tbody>
            {[data.subject, medianRow, ...data.peers].map((row, i) => {
              const isSubject = row.startup_id === data.subject.startup_id;
              const isMedian = row.startup_id === "__median__";
              return (
                <m.tr
                  key={row.startup_id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i * 0.04, 0.4), duration: 0.35 }}
                  className={`border-b border-grid last:border-0 ${
                    isSubject ? "bg-brand-tint/60" : isMedian ? "bg-raised/60" : "hover:bg-raised/50"
                  }`}
                >
                  <td
                    className={`sticky left-0 z-10 px-5 py-3 ${
                      isSubject ? "bg-brand-tint" : isMedian ? "bg-raised" : "bg-surface"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      {!isMedian && <LogoTile name={row.legal_name} src={row.logo_url} size={26} />}
                      <div className="min-w-0">
                        {isMedian ? (
                          <span className="text-[13px] font-semibold italic text-ink-muted">
                            {row.legal_name}
                          </span>
                        ) : (
                          <Link
                            to={`/startup/${row.startup_id}`}
                            className="block truncate text-[13.5px] font-bold hover:text-brand-text"
                          >
                            {row.legal_name}
                          </Link>
                        )}
                        {isSubject && <span className="text-[11px] font-bold text-brand-text">This company</span>}
                        {!isSubject && !isMedian && row.hq_city && (
                          <span className="block truncate text-[11.5px] text-ink-muted">{row.hq_city}</span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-[12.5px] text-ink-secondary">
                    {isMedian ? "—" : stageLabel(row.stage)}
                  </td>
                  {METRICS.map((mt) => (
                    <Cell key={String(mt.key)} row={row} metric={mt} max={maxes[String(mt.key)]} />
                  ))}
                  <td className="px-3 py-3 text-right">
                    {isSubject || isMedian ? (
                      <span className="text-[12px] text-ink-muted">—</span>
                    ) : (
                      <span className="tnum text-[12.5px] text-ink-secondary">
                        {row.similarity != null ? `${(row.similarity * 100).toFixed(0)}%` : "—"}
                      </span>
                    )}
                  </td>
                </m.tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="border-t border-line px-5 py-3 text-[12px] leading-relaxed text-ink-muted sm:px-6">
        Bars are each column's share of the largest value on screen. Revenue is modelled for
        corpus companies — see the note on their own pages.
      </p>
    </Card>
  );
}
