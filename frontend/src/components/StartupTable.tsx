import { Link } from "react-router-dom";
import type { StartupSummary } from "../lib/api";
import { compactUsd, fraudBand, scoreBand, stageLabel } from "../lib/format";
import { LogoTile, VerifiedBadge } from "./primitives";

type Col = { key: string; label: string; sort?: string };

const COLS: Col[] = [
  { key: "composite", label: "Score", sort: "composite_score" },
  { key: "growth", label: "Growth", sort: "growth" },
  { key: "risk", label: "Safety", sort: "risk" },
  { key: "founder", label: "Founder", sort: "founder" },
  { key: "fraud", label: "Fraud ↓" },
];

const scoreOf = (s: StartupSummary, key: string) =>
  ({
    composite: s.composite_score,
    growth: s.growth_potential_score,
    risk: s.risk_level_score,
    founder: s.founder_credibility_score,
    fraud: s.fraud_likelihood_score,
  })[key] ?? null;

/** Dense comparison table, Crunchbase-style: identity column with logo,
 *  sortable score columns, numerals coloured by band (never cell fills). */
export function StartupTable({
  items,
  sortKey,
  onSort,
  onOpen,
}: {
  items: StartupSummary[];
  sortKey?: string;
  onSort?: (key: string) => void;
  onOpen?: (id: string) => void;
}) {
  return (
    <div className="card card-lit overflow-x-auto">
      <table className="data-table min-w-[700px]">
        <thead>
          <tr>
            <th className="col-sticky text-left">Organization name</th>
            <th className="text-left">Industry · stage</th>
            <th className="hidden text-left 2xl:table-cell">Headquarters</th>
            {COLS.map((c) => {
              const active = c.sort && c.sort === sortKey;
              return (
                <th key={c.key} className="px-2.5! text-right" aria-sort={active ? "descending" : undefined}>
                  {c.sort && onSort ? (
                    <button
                      onClick={() => onSort(c.sort!)}
                      className={`inline-flex items-center gap-1 uppercase tracking-[0.06em] transition-colors hover:text-ink ${
                        active ? "text-ink" : ""
                      }`}
                    >
                      {c.label}
                      {active && <span aria-hidden>↓</span>}
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              );
            })}
            <th className="text-right">Raised</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.startup_id}>
              <td className="col-sticky">
                <Link
                  to={`/startup/${s.startup_id}`}
                  onClick={() => onOpen?.(s.startup_id)}
                  className="flex min-w-0 items-center gap-3"
                >
                  <LogoTile name={s.legal_name} src={s.logo_url} size={32} />
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[190px] truncate font-bold text-brand-text hover:underline">{s.legal_name}</span>
                      <VerifiedBadge verified={s.verified} compact />
                    </span>
                    <span className="block max-w-[210px] truncate text-[12px] text-ink-muted">
                      {s.one_liner ?? s.sub_vertical ?? "—"}
                    </span>
                  </span>
                </Link>
              </td>
              <td className="text-ink-secondary">
                <span className="block whitespace-nowrap">{s.sector}</span>
                <span className="block whitespace-nowrap text-[12px] text-ink-muted">{stageLabel(s.stage)}</span>
              </td>
              <td className="hidden whitespace-nowrap text-ink-secondary 2xl:table-cell">{s.hq_city ?? "—"}</td>
              {COLS.map((c) => {
                const v = scoreOf(s, c.key);
                const colour = c.key === "fraud" ? fraudBand(v).color : scoreBand(v).color;
                const emphasised = c.sort && c.sort === sortKey;
                return (
                  <td key={c.key} className="px-2.5! text-right">
                    <span
                      className="tnum"
                      style={{
                        color: colour,
                        opacity: sortKey && c.sort && !emphasised ? 0.6 : 1,
                        fontWeight: emphasised ? 700 : 500,
                      }}
                    >
                      {v === null ? "—" : c.key === "composite" ? v.toFixed(1) : Math.round(v)}
                    </span>
                  </td>
                );
              })}
              <td className="tnum whitespace-nowrap text-right text-ink-secondary">{compactUsd(s.total_funding_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
